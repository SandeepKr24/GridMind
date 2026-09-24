"""The ingestion job runner: stages, failures, limits and orphaned jobs.

The store and the provider are in-memory doubles. The one-job-per-session
guarantee in Postgres is covered by `test_jobs_store.py`; this file covers what
the runner does around it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading

import pytest

from app.db.models.enums import ACTIVE_STATUSES, JobStage, JobStatus, SessionType
from app.ingestion.base import ProviderError, RawSession, SessionNotAvailableError
from app.ingestion.jobs import JobKey, JobRecord
from app.ingestion.normalizer import StoredSession
from app.ingestion.runner import INTERRUPTED, PROVIDER_FAILED, IngestBusyError, JobRunner
from tests.conftest_db import sample_session

pytestmark = pytest.mark.asyncio

KEY = JobKey(2024, 14, SessionType.RACE)
OTHER = JobKey(2024, 15, SessionType.RACE)


class StoreDouble:
    """Job rows in a dict, with the partial-unique-index rule applied."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}
        self.ingested: set[JobKey] = set()
        self.stages: dict[str, list[JobStage]] = {}
        self.complete = True
        self._next = 0

    def _new(self, key: JobKey, status: JobStatus) -> str:
        self._next += 1
        job_id = f"job-{self._next}"
        self.jobs[job_id] = JobRecord(
            id=job_id,
            season_year=key.season_year,
            round_number=key.round_number,
            session_type=key.session_type,
            status=status,
            stage=JobStage.RESOLVING,
            progress_percent=None,
            started_at=None,
            finished_at=None,
            error_message=None,
            rows_written=None,
        )
        self.stages[job_id] = [JobStage.RESOLVING]
        return job_id

    def _set(self, job_id: str, **changes: object) -> None:
        self.jobs[job_id] = dataclasses.replace(self.jobs[job_id], **changes)  # type: ignore[arg-type]

    @staticmethod
    def _key(job: JobRecord) -> JobKey:
        return JobKey(job.season_year, job.round_number, job.session_type)

    async def is_ingested(self, key: JobKey) -> bool:
        return key in self.ingested

    async def find_active(self, key: JobKey) -> str | None:
        for job in self.jobs.values():
            if self._key(job) == key and job.status in ACTIVE_STATUSES:
                return job.id
        return None

    async def claim(self, key: JobKey) -> str | None:
        if await self.find_active(key) is not None:
            return None
        return self._new(key, JobStatus.PENDING)

    async def record_cached(self, key: JobKey) -> str:
        return self._new(key, JobStatus.SKIPPED_CACHED)

    async def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def start(self, job_id: str) -> None:
        self._set(job_id, status=JobStatus.RUNNING)

    async def advance(self, job_id: str, stage: JobStage) -> None:
        self._set(job_id, stage=stage)
        self.stages[job_id].append(stage)

    async def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        rows_written: int | None = None,
        error: str | None = None,
    ) -> None:
        self._set(job_id, status=status, rows_written=rows_written, error_message=error)

    async def store_session(self, raw: RawSession) -> StoredSession:
        if self.complete:
            self.ingested.add(KEY)
        return StoredSession(
            session_id=1, meeting_id=1, rows_written=raw.row_count, is_complete=self.complete
        )


class ProviderDouble:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.gate = threading.Event()
        self.gate.set()
        self.calls: list[JobKey] = []

    def fetch_session(
        self, season: int, round_number: int, session_type: SessionType
    ) -> RawSession:
        self.calls.append(JobKey(season, round_number, session_type))
        self.gate.wait(timeout=5)
        if self.error is not None:
            raise self.error
        return sample_session()


def runner(
    store: StoreDouble,
    provider: ProviderDouble,
    *,
    max_concurrent: int = 2,
    max_pending: int = 8,
    timeout: float = 5,
) -> JobRunner:
    return JobRunner(
        store,
        provider,
        max_concurrent=max_concurrent,
        max_pending=max_pending,
        timeout_seconds=timeout,
    )


async def finished(store: StoreDouble, jobs: JobRunner, job_id: str) -> JobRecord:
    await jobs.wait_idle()
    record = store.jobs[job_id]
    assert record.status not in ACTIVE_STATUSES
    return record


class TestHappyPath:
    async def test_fetches_stores_and_succeeds(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        jobs = runner(store, provider)

        submission = await jobs.submit(KEY)
        job = await finished(store, jobs, submission.job_id)

        assert submission.is_new
        assert job.status == JobStatus.SUCCEEDED
        assert job.rows_written == sample_session().row_count
        assert provider.calls == [KEY]

    async def test_stages_are_reported_in_order(self) -> None:
        # The Loading Pit lights one lamp per reported stage, never on a timer.
        store = StoreDouble()
        jobs = runner(store, ProviderDouble())

        submission = await jobs.submit(KEY)
        await jobs.wait_idle()

        assert store.stages[submission.job_id] == [
            JobStage.RESOLVING,
            JobStage.FETCHING,
            JobStage.STORING,
            JobStage.VERIFYING,
        ]


class TestNoWastedFetches:
    async def test_a_stored_session_is_answered_without_a_fetch(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        store.ingested.add(KEY)
        jobs = runner(store, provider)

        submission = await jobs.submit(KEY)

        assert not submission.is_new
        assert store.jobs[submission.job_id].status == JobStatus.SKIPPED_CACHED
        assert provider.calls == []

    async def test_a_second_request_attaches_to_the_running_job(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider)

        first = await jobs.submit(KEY)
        second = await jobs.submit(KEY)
        provider.gate.set()
        await jobs.wait_idle()

        assert second.job_id == first.job_id
        assert not second.is_new
        assert provider.calls == [KEY]

    async def test_simultaneous_requests_make_one_job(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider)

        submissions = await asyncio.gather(*(jobs.submit(KEY) for _ in range(5)))
        provider.gate.set()
        await jobs.wait_idle()

        assert len({s.job_id for s in submissions}) == 1
        assert provider.calls == [KEY]

    async def test_a_session_stored_while_queued_is_not_fetched_again(self) -> None:
        # Another path (the script, a racing process) can finish it first.
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider, max_concurrent=1)

        await jobs.submit(OTHER)
        queued = await jobs.submit(KEY)
        store.ingested.add(KEY)
        provider.gate.set()
        job = await finished(store, jobs, queued.job_id)

        assert job.status == JobStatus.SKIPPED_CACHED
        assert provider.calls == [OTHER]


class TestFailures:
    async def test_a_session_with_no_data_yet_says_so(self) -> None:
        store = StoreDouble()
        provider = ProviderDouble(
            error=SessionNotAvailableError(
                "timing data for 2024 round 14 race is not available yet"
            )
        )
        jobs = runner(store, provider)

        job = await finished(store, jobs, (await jobs.submit(KEY)).job_id)

        assert job.status == JobStatus.FAILED
        assert job.error_message == "Timing data for 2024 round 14 race is not available yet."

    async def test_a_provider_failure_does_not_leak_upstream_detail(self) -> None:
        store = StoreDouble()
        provider = ProviderDouble(error=ProviderError("HTTP 503 from livetiming.formula1.com"))
        jobs = runner(store, provider)

        job = await finished(store, jobs, (await jobs.submit(KEY)).job_id)

        assert job.status == JobStatus.FAILED
        assert job.error_message is not None
        assert "livetiming" not in job.error_message
        assert "try again" in job.error_message.lower()

    async def test_an_unexpected_error_fails_the_job_instead_of_hanging_it(self) -> None:
        store = StoreDouble()
        jobs = runner(store, ProviderDouble(error=KeyError("DriverId")))

        job = await finished(store, jobs, (await jobs.submit(KEY)).job_id)

        assert job.status == JobStatus.FAILED
        assert "DriverId" not in (job.error_message or "")

    async def test_a_stuck_fetch_times_out(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider, timeout=0.1)

        job = await finished(store, jobs, (await jobs.submit(KEY)).job_id)
        provider.gate.set()

        assert job.status == JobStatus.FAILED
        assert "longer than" in (job.error_message or "")

    async def test_incomplete_data_is_not_reported_as_success(self) -> None:
        # Otherwise the race reads "available" again after a "successful" fetch
        # and the page loops.
        store = StoreDouble()
        store.complete = False
        jobs = runner(store, ProviderDouble())

        job = await finished(store, jobs, (await jobs.submit(KEY)).job_id)

        assert job.status == JobStatus.FAILED
        assert job.rows_written == sample_session().row_count
        assert "incomplete" in (job.error_message or "")

    async def test_a_failed_job_can_be_retried(self) -> None:
        store = StoreDouble()
        provider = ProviderDouble(error=ProviderError("down"))
        jobs = runner(store, provider)
        first = await jobs.submit(KEY)
        await jobs.wait_idle()

        provider.error = None
        second = await jobs.submit(KEY)
        job = await finished(store, jobs, second.job_id)

        assert second.job_id != first.job_id
        assert job.status == JobStatus.SUCCEEDED


class TestLimits:
    async def test_at_most_max_concurrent_fetches_run_at_once(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider, max_concurrent=1)

        await jobs.submit(KEY)
        await jobs.submit(OTHER)
        await asyncio.sleep(0.1)

        assert provider.calls == [KEY]
        provider.gate.set()
        await jobs.wait_idle()
        assert provider.calls == [KEY, OTHER]

    async def test_a_full_queue_refuses_new_sessions(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider, max_pending=1)

        await jobs.submit(KEY)
        with pytest.raises(IngestBusyError):
            await jobs.submit(OTHER)
        provider.gate.set()
        await jobs.wait_idle()

    async def test_a_full_queue_still_attaches_to_a_running_job(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider, max_pending=1)

        first = await jobs.submit(KEY)
        again = await jobs.submit(KEY)
        provider.gate.set()
        await jobs.wait_idle()

        assert again.job_id == first.job_id


class TestOrphans:
    """A live job row this process does not own was left by a restart."""

    async def test_polling_an_orphan_marks_it_interrupted(self) -> None:
        store = StoreDouble()
        orphan = await store.claim(KEY)
        assert orphan is not None
        jobs = runner(store, ProviderDouble())

        job = await jobs.get(orphan)

        assert job is not None
        assert (job.status, job.error_message) == (JobStatus.FAILED, INTERRUPTED)

    async def test_an_orphan_does_not_block_a_new_request(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        orphan = await store.claim(KEY)
        jobs = runner(store, provider)

        submission = await jobs.submit(KEY)
        await jobs.wait_idle()

        assert submission.job_id != orphan
        assert store.jobs[submission.job_id].status == JobStatus.SUCCEEDED

    async def test_a_job_this_process_is_running_is_not_an_orphan(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider)

        submission = await jobs.submit(KEY)
        job = await jobs.get(submission.job_id)
        provider.gate.set()
        await jobs.wait_idle()

        assert job is not None
        assert job.status in ACTIVE_STATUSES

    async def test_an_unknown_job_is_none(self) -> None:
        assert await runner(StoreDouble(), ProviderDouble()).get("nope") is None

    async def test_a_lost_final_write_keeps_the_real_reason(self) -> None:
        # The job ran here and failed, but recording that failed too (a Neon
        # blip). It is not a restart, and must not be reported as one.
        store = StoreDouble()
        real_finish = store.finish
        attempts = 0

        async def flaky_finish(job_id: str, status: JobStatus, **kwargs: object) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("connection dropped")
            await real_finish(job_id, status, **kwargs)  # type: ignore[arg-type]

        store.finish = flaky_finish  # type: ignore[method-assign]
        jobs = runner(store, ProviderDouble(error=ProviderError("down")))
        submission = await jobs.submit(KEY)
        await jobs.wait_idle()

        job = await jobs.get(submission.job_id)

        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.error_message == PROVIDER_FAILED


class TestShutdown:
    async def test_shutdown_cancels_running_jobs(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()
        jobs = runner(store, provider)
        await jobs.submit(KEY)

        await jobs.shutdown()
        provider.gate.set()

        # The row stays live; the next process sees it as an orphan.
        assert await jobs.wait_idle() is None
