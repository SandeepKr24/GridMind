"""Report generation as a background job the Loading Pit can follow.

The race page polls `GET /api/jobs/{id}` for reports exactly as it does for
ingestion, so a report job reports the same `JobRecord` and the same five
stages:

    resolving  -> is there a report already? is the race stored?
    fetching   -> ingest the race session, via the ingestion runner,
    storing       whose own stages are mirrored here
    verifying  -> check the data is complete and build the facts
    answering  -> the model writes, the checks run, the report is stored

Jobs live in memory, not in `ingestion_jobs`: that table's one-live-job-per-
session lock would collide with the race's own ingestion job, and a report
job is short. A restart loses a job in flight; the report itself, once
stored, is permanent.

One report is written at a time. A single request reserves most of the free
tier's per-minute token budget, so two at once would only rate-limit each
other.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.db.models.enums import JobStage, JobStatus, ReportTrigger, SessionType
from app.ingestion.jobs import JobKey, JobRecord
from app.ingestion.runner import Submission
from app.llm import LLMError, LLMProvider, LLMRateLimitedError
from app.reports.facts import IncompleteRaceError, ReportFacts
from app.reports.writer import ReportRejectedError, WrittenReport, write_report

logger = logging.getLogger(__name__)

#: Report job ids carry this, so the jobs route can tell them from ingestion ids.
JOB_PREFIX = "report-"
POLL_SECONDS = 1.0
#: A rate limit asking for longer than this is a daily quota; fail instead.
MAX_RATE_LIMIT_WAIT = 90.0
#: Finished jobs kept for polling after they end.
MAX_FINISHED = 200

REJECTED = "The AI model could not write a report that matched the race data. Try again later."
MODEL_DOWN = "The AI model is unavailable right now. Try again later."
UNEXPECTED = "Something went wrong while writing this report. Try again."
STOPPED = "The server stopped before this report was finished. Try again."


class ReportBusyError(RuntimeError):
    """Too many reports are already queued to accept another."""


class IngestionRunner(Protocol):
    async def is_ingested(self, key: JobKey) -> bool: ...
    async def submit(self, key: JobKey) -> Submission: ...
    async def get(self, job_id: str) -> JobRecord | None: ...


class FactsSource(Protocol):
    async def load(self, season: int, round_number: int) -> ReportFacts: ...


class ReportArchive(Protocol):
    async def exists(self, season: int, round_number: int) -> bool: ...
    async def save(
        self, season: int, round_number: int, report: WrittenReport, trigger: ReportTrigger
    ) -> int: ...


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(slots=True)
class _Job:
    record: JobRecord
    trigger: ReportTrigger
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def update(self, **changes: object) -> None:
        self.record = replace(self.record, **changes)  # type: ignore[arg-type]


class ReportJobs:
    def __init__(
        self,
        llm: LLMProvider,
        ingestion: IngestionRunner,
        facts: FactsSource,
        archive: ReportArchive,
        *,
        max_pending: int = 3,
        timeout_seconds: float = 600.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._llm = llm
        self._ingestion = ingestion
        self._facts = facts
        self._archive = archive
        self._max_pending = max_pending
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._writing = asyncio.Semaphore(1)
        self._submitting = asyncio.Lock()
        self._jobs: OrderedDict[str, _Job] = OrderedDict()

    def get(self, job_id: str) -> JobRecord | None:
        job = self._jobs.get(job_id)
        return job.record if job else None

    async def submit(
        self, season: int, round_number: int, trigger: ReportTrigger = ReportTrigger.ON_REQUEST
    ) -> str:
        """A job id for the race's report: new, running, or already done."""
        # One submit at a time: the duplicate check and the job it creates are
        # separated by a database round trip, and two clicks on "Generate"
        # would otherwise both pass the check and pay for two reports.
        async with self._submitting:
            return await self._submit(season, round_number, trigger)

    async def _submit(self, season: int, round_number: int, trigger: ReportTrigger) -> str:
        for job in self._jobs.values():
            record = job.record
            if record.is_active and (record.season_year, record.round_number) == (
                season,
                round_number,
            ):
                return record.id

        if await self._archive.exists(season, round_number):
            return self._add(season, round_number, trigger, JobStatus.SKIPPED_CACHED).record.id

        if sum(job.record.is_active for job in self._jobs.values()) >= self._max_pending:
            raise ReportBusyError("too many reports are already queued")
        job = self._add(season, round_number, trigger, JobStatus.PENDING)
        job.task = asyncio.create_task(self._run(job), name=f"report-{job.record.id}")
        return job.record.id

    async def wait_idle(self) -> None:
        """Wait for every running job. For tests and shutdown."""
        tasks = [j.task for j in self._jobs.values() if j.task is not None and not j.task.done()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        for job in self._jobs.values():
            if job.task is not None:
                job.task.cancel()
        await self.wait_idle()

    def _add(
        self, season: int, round_number: int, trigger: ReportTrigger, status: JobStatus
    ) -> _Job:
        finished = status is JobStatus.SKIPPED_CACHED
        record = JobRecord(
            id=JOB_PREFIX + secrets.token_urlsafe(12),
            season_year=season,
            round_number=round_number,
            session_type=SessionType.RACE,
            status=status,
            stage=JobStage.RESOLVING,
            progress_percent=None,
            started_at=_now(),
            finished_at=_now() if finished else None,
            error_message=None,
            rows_written=0 if finished else None,
        )
        job = _Job(record, trigger)
        self._jobs[record.id] = job
        self._forget_old()
        return job

    def _forget_old(self) -> None:
        finished = [i for i, j in self._jobs.items() if not j.record.is_active]
        for job_id in finished[: max(len(finished) - MAX_FINISHED, 0)]:
            del self._jobs[job_id]

    async def _run(self, job: _Job) -> None:
        try:
            async with self._writing, asyncio.timeout(self._timeout):
                job.update(status=JobStatus.RUNNING)
                await self._generate(job)
        except TimeoutError:
            self._fail(job, f"Writing the report took longer than {self._timeout:g} seconds.")
        except (IncompleteRaceError, _IngestionFailedError) as error:
            self._fail(job, str(error))
        except ReportRejectedError:
            logger.warning("report %s: rejected after retries", job.record.id)
            self._fail(job, REJECTED)
        except LLMError:
            logger.exception("report %s: the model failed", job.record.id)
            self._fail(job, MODEL_DOWN)
        except Exception:
            logger.exception("report %s: unexpected failure", job.record.id)
            self._fail(job, UNEXPECTED)
        except asyncio.CancelledError:
            # Not an Exception, so nothing above catches it. Without this, a
            # job cancelled at shutdown would read "running" forever.
            self._fail(job, STOPPED)
            raise

    async def _generate(self, job: _Job) -> None:
        season, round_number = job.record.season_year, job.record.round_number
        await self._ensure_ingested(job, JobKey(season, round_number, SessionType.RACE))

        job.update(stage=JobStage.VERIFYING)
        facts = await self._facts.load(season, round_number)

        job.update(stage=JobStage.ANSWERING)
        report = await self._write(facts)
        await self._archive.save(season, round_number, report, job.trigger)
        job.update(
            status=JobStatus.SUCCEEDED, finished_at=_now(), rows_written=len(report.sections)
        )
        logger.info("report %s: stored %s round %s", job.record.id, season, round_number)

    async def _ensure_ingested(self, job: _Job, key: JobKey) -> None:
        if await self._ingestion.is_ingested(key):
            return
        ingest_id = (await self._ingestion.submit(key)).job_id
        while True:
            record = await self._ingestion.get(ingest_id)
            if record is None:
                raise _IngestionFailedError("The race data could not be fetched. Try again.")
            if not record.is_active:
                if record.status in (JobStatus.SUCCEEDED, JobStatus.SKIPPED_CACHED):
                    return
                raise _IngestionFailedError(record.error_message or "The race data fetch failed.")
            # Show the fetch's own progress on the report's lights.
            job.update(stage=record.stage)
            await self._sleep(POLL_SECONDS)

    async def _write(self, facts: ReportFacts) -> WrittenReport:
        try:
            return await write_report(self._llm, facts)
        except LLMRateLimitedError as error:
            wait = error.retry_after
            if wait is None or wait > MAX_RATE_LIMIT_WAIT:
                raise
            # No HTTP request is waiting on this job, so a short wait is free.
            logger.info("report: rate limited, waiting %.0fs", wait)
            await self._sleep(wait + 1)
            return await write_report(self._llm, facts)

    def _fail(self, job: _Job, message: str) -> None:
        job.update(status=JobStatus.FAILED, finished_at=_now(), error_message=message)


class _IngestionFailedError(RuntimeError):
    """The race could not be fetched. The message is the fetch's own, for the user."""
