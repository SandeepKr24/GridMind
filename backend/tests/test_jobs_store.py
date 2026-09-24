"""Job rows against the real database.

The one-job-per-session guarantee is a Postgres partial unique index, so it is
tested against Postgres. Every test runs in a rolled-back transaction.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models.enums import JobStage, JobStatus, SessionType
from app.ingestion import jobs
from app.ingestion.jobs import JobKey
from app.ingestion.normalizer import SessionWriter
from tests.conftest_db import (  # noqa: F401
    TEST_SEASON,
    connection,
    database,
    sample_session,
)

pytestmark = pytest.mark.asyncio

KEY = JobKey(TEST_SEASON, 1, SessionType.RACE)

# What the frontend accepts in `?job=`.
FRONTEND_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TestClaim:
    async def test_a_new_claim_creates_a_pending_job(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        job_id = await jobs.claim(connection, KEY)

        assert job_id is not None
        assert FRONTEND_JOB_ID.match(job_id)
        job = await jobs.get(connection, job_id)
        assert job is not None
        assert (job.status, job.stage) == (JobStatus.PENDING, JobStage.RESOLVING)
        assert (job.season_year, job.round_number, job.session_type) == (
            TEST_SEASON,
            1,
            SessionType.RACE,
        )

    async def test_a_second_claim_for_a_live_session_is_refused(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        first = await jobs.claim(connection, KEY)

        assert await jobs.claim(connection, KEY) is None
        assert await jobs.find_active(connection, KEY) == first

    async def test_other_sessions_are_independent(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await jobs.claim(connection, KEY)
        other = JobKey(TEST_SEASON, 1, SessionType.QUALIFYING)
        assert await jobs.claim(connection, other) is not None

    async def test_a_finished_job_frees_the_slot(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Failed jobs pile up as history; they must not block a retry.
        first = await jobs.claim(connection, KEY)
        assert first is not None
        await jobs.finish(connection, first, JobStatus.FAILED, error="upstream down")

        assert await jobs.find_active(connection, KEY) is None
        assert await jobs.claim(connection, KEY) is not None

    async def test_a_running_job_still_holds_the_slot(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        first = await jobs.claim(connection, KEY)
        assert first is not None
        await jobs.start(connection, first)
        assert await jobs.claim(connection, KEY) is None


class TestLifecycle:
    async def test_start_records_when_it_began(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        job_id = await jobs.claim(connection, KEY)
        assert job_id is not None

        await jobs.start(connection, job_id)

        job = await jobs.get(connection, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None

    async def test_stages_advance(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        job_id = await jobs.claim(connection, KEY)
        assert job_id is not None

        await jobs.advance(connection, job_id, JobStage.STORING)

        job = await jobs.get(connection, job_id)
        assert job is not None
        assert job.stage == JobStage.STORING

    async def test_success_records_rows_and_finish_time(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        job_id = await jobs.claim(connection, KEY)
        assert job_id is not None

        await jobs.finish(connection, job_id, JobStatus.SUCCEEDED, rows_written=917)

        job = await jobs.get(connection, job_id)
        assert job is not None
        assert (job.status, job.rows_written, job.error_message) == (
            JobStatus.SUCCEEDED,
            917,
            None,
        )
        assert job.finished_at is not None

    async def test_an_unknown_job_is_none(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        assert await jobs.get(connection, "no-such-job") is None


class TestCached:
    async def test_nothing_is_ingested_by_default(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        assert await jobs.is_ingested(connection, KEY) is False

    async def test_a_stored_session_is_ingested(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        assert await jobs.is_ingested(connection, KEY) is True

    async def test_a_cached_record_is_already_finished(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # The frontend treats skipped_cached as done and never shows the pit.
        job_id = await jobs.record_cached(connection, KEY)

        job = await jobs.get(connection, job_id)
        assert job is not None
        assert job.status == JobStatus.SKIPPED_CACHED
        assert job.finished_at is not None
        assert await jobs.find_active(connection, KEY) is None
