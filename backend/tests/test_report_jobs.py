"""Report jobs: stages, de-duplication, the cached shortcut, fetching first, failures."""

from __future__ import annotations

import asyncio

import pytest

from app.db.models.enums import JobStage, JobStatus, ReportTrigger, SessionType
from app.ingestion.jobs import JobKey, JobRecord
from app.ingestion.runner import Submission
from app.llm import LLMRateLimitedError
from app.reports.facts import IncompleteRaceError, ReportFacts
from app.reports.jobs import (
    JOB_PREFIX,
    MODEL_DOWN,
    REJECTED,
    STOPPED,
    ReportBusyError,
    ReportJobs,
)
from app.reports.writer import WrittenReport
from tests.test_report_writer import FACTS, ScriptedLLM, good_report

KEY = JobKey(2024, 14, SessionType.RACE)


class Ingestion:
    """Stores nothing until asked; a submitted fetch finishes on the next poll."""

    def __init__(self, *, stored: bool = True, fails_with: str | None = None) -> None:
        self.stored = stored
        self.fails_with = fails_with
        self.submitted: list[JobKey] = []
        self._polls = 0

    async def is_ingested(self, key: JobKey) -> bool:
        return self.stored

    async def submit(self, key: JobKey) -> Submission:
        self.submitted.append(key)
        return Submission("ingest-1", is_new=True)

    async def get(self, job_id: str) -> JobRecord | None:
        self._polls += 1
        running = self._polls == 1
        status = JobStatus.RUNNING if running else JobStatus.SUCCEEDED
        if not running and self.fails_with:
            status = JobStatus.FAILED
        return JobRecord(
            id=job_id,
            season_year=2024,
            round_number=14,
            session_type=SessionType.RACE,
            status=status,
            stage=JobStage.FETCHING if running else JobStage.VERIFYING,
            progress_percent=None,
            started_at=None,
            finished_at=None,
            error_message=None if running else self.fails_with,
            rows_written=None,
        )


class Facts:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def load(self, season: int, round_number: int) -> ReportFacts:
        if self.error:
            raise self.error
        return FACTS


class Archive:
    def __init__(self, *, existing: bool = False) -> None:
        self.existing = existing
        self.saved: list[tuple[int, int, WrittenReport, ReportTrigger]] = []

    async def exists(self, season: int, round_number: int) -> bool:
        return self.existing

    async def save(
        self, season: int, round_number: int, report: WrittenReport, trigger: ReportTrigger
    ) -> int:
        self.saved.append((season, round_number, report, trigger))
        return 1


class Harness:
    def __init__(
        self,
        *replies: str | Exception,
        ingestion: Ingestion | None = None,
        facts: Facts | None = None,
        archive: Archive | None = None,
        max_pending: int = 3,
    ) -> None:
        self.llm = ScriptedLLM(*(replies or (good_report(),)))
        self.ingestion = ingestion or Ingestion()
        self.archive = archive or Archive()
        self.slept: list[float] = []

        async def sleep(seconds: float) -> None:
            self.slept.append(seconds)

        self.jobs = ReportJobs(
            self.llm,
            self.ingestion,
            facts or Facts(),
            self.archive,
            max_pending=max_pending,
            sleep=sleep,
        )

    async def run(self) -> JobRecord:
        job_id = await self.jobs.submit(2024, 14)
        await self.jobs.wait_idle()
        record = self.jobs.get(job_id)
        assert record is not None
        return record


class TestHappyPath:
    async def test_a_stored_race_is_written_up_and_saved(self) -> None:
        harness = Harness()

        record = await harness.run()

        assert record.status is JobStatus.SUCCEEDED
        assert record.id.startswith(JOB_PREFIX)
        assert (record.season_year, record.round_number) == (2024, 14)
        assert record.finished_at is not None
        (season, round_number, report, trigger) = harness.archive.saved[0]
        assert (season, round_number, trigger) == (2024, 14, ReportTrigger.ON_REQUEST)
        assert len(report.sections) == 7
        assert harness.ingestion.submitted == []

    async def test_an_existing_report_is_a_finished_job_and_spends_nothing(self) -> None:
        harness = Harness(archive=Archive(existing=True))

        record = await harness.run()

        assert record.status is JobStatus.SKIPPED_CACHED
        assert harness.llm.prompts == []

    async def test_asking_twice_while_running_returns_the_same_job(self) -> None:
        harness = Harness()

        first = await harness.jobs.submit(2024, 14)
        second = await harness.jobs.submit(2024, 14)
        await harness.jobs.wait_idle()

        assert first == second
        assert len(harness.llm.prompts) == 1

    async def test_simultaneous_requests_for_one_race_make_one_job(self) -> None:
        # Two clicks at once both passed the duplicate check while the first
        # was still asking the database whether a report existed.
        class SlowArchive(Archive):
            async def exists(self, season: int, round_number: int) -> bool:
                await asyncio.sleep(0)  # a database round trip
                return bool(self.saved)

        harness = Harness(archive=SlowArchive())

        await asyncio.gather(harness.jobs.submit(2024, 14), harness.jobs.submit(2024, 14))
        await harness.jobs.wait_idle()

        # The second request either joins the running job or, if the first
        # already finished, gets the stored report. Never a second write.
        assert len(harness.llm.prompts) == 1
        assert len(harness.archive.saved) == 1

    async def test_a_job_cancelled_at_shutdown_does_not_stay_running(self) -> None:
        started = asyncio.Event()

        class StuckFacts(Facts):
            async def load(self, season: int, round_number: int) -> ReportFacts:
                started.set()
                await asyncio.sleep(60)
                return FACTS

        harness = Harness(facts=StuckFacts())
        job_id = await harness.jobs.submit(2024, 14)
        await started.wait()

        await harness.jobs.shutdown()

        record = harness.jobs.get(job_id)
        assert record is not None
        assert (record.status, record.error_message) == (JobStatus.FAILED, STOPPED)
        assert record.finished_at is not None

    async def test_an_unknown_job_is_none(self) -> None:
        assert Harness().jobs.get("report-nope") is None


class TestFetchingFirst:
    async def test_a_race_not_stored_is_fetched_then_written(self) -> None:
        harness = Harness(ingestion=Ingestion(stored=False))

        record = await harness.run()

        assert record.status is JobStatus.SUCCEEDED
        assert harness.ingestion.submitted == [KEY]
        assert harness.slept == [1.0]  # one poll while the fetch ran

    async def test_a_failed_fetch_fails_the_report_with_its_message(self) -> None:
        harness = Harness(ingestion=Ingestion(stored=False, fails_with="No timing data yet."))

        record = await harness.run()

        assert (record.status, record.error_message) == (JobStatus.FAILED, "No timing data yet.")
        assert harness.llm.prompts == []


class TestFailures:
    async def test_an_incomplete_race_says_what_is_missing(self) -> None:
        harness = Harness(facts=Facts(IncompleteRaceError("The race has no winner recorded yet.")))

        record = await harness.run()

        assert record.error_message == "The race has no winner recorded yet."
        assert harness.archive.saved == []

    async def test_a_report_that_keeps_failing_its_checks_is_not_stored(self) -> None:
        bad = good_report(Strategy="The undercut was worth 3.456 seconds to Hamilton that day.")
        harness = Harness(bad, bad)

        record = await harness.run()

        assert (record.status, record.error_message) == (JobStatus.FAILED, REJECTED)
        assert harness.archive.saved == []

    async def test_a_short_rate_limit_is_waited_out(self) -> None:
        harness = Harness(LLMRateLimitedError("TPM", retry_after=20), good_report())

        record = await harness.run()

        assert record.status is JobStatus.SUCCEEDED
        assert harness.slept == [21]

    async def test_a_long_rate_limit_fails_the_job(self) -> None:
        harness = Harness(LLMRateLimitedError("TPD", retry_after=3600))

        record = await harness.run()

        assert (record.status, record.error_message) == (JobStatus.FAILED, MODEL_DOWN)

    async def test_a_full_queue_refuses_another_race(self) -> None:
        gate = asyncio.Event()

        class SlowFacts(Facts):
            async def load(self, season: int, round_number: int) -> ReportFacts:
                await gate.wait()
                return FACTS

        harness = Harness(facts=SlowFacts(), max_pending=1)
        await harness.jobs.submit(2024, 14)

        with pytest.raises(ReportBusyError):
            await harness.jobs.submit(2024, 13)

        gate.set()
        await harness.jobs.wait_idle()

    async def test_a_job_that_runs_too_long_is_failed(self) -> None:
        class StuckFacts(Facts):
            async def load(self, season: int, round_number: int) -> ReportFacts:
                await asyncio.sleep(5)
                return FACTS

        harness = Harness(facts=StuckFacts())
        harness.jobs._timeout = 0.05  # a 10-minute ceiling is not testable

        record = await harness.run()

        assert record.status is JobStatus.FAILED
        assert "took longer" in (record.error_message or "")
