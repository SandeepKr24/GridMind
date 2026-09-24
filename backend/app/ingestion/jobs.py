"""Job rows: the SQL behind on-demand ingestion.

Every function takes a connection and leaves transaction control to the caller,
so each can be tested inside a rolled-back transaction and the runner decides
what commits when.

The one-job-per-session guarantee is not enforced here. It is the partial
unique index on `ingestion_jobs` (see `app/db/models/jobs.py`): a claim is an
insert that does nothing on conflict, so two simultaneous claims for the same
session cannot both succeed however they interleave.
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import IngestionJob, Meeting, Season, Session
from app.db.models.enums import ACTIVE_STATUSES, JobStage, JobStatus, SessionType

#: 16 random bytes, URL-safe: 22 characters inside the frontend's
#: ^[A-Za-z0-9_-]{1,64}$ and not guessable from a neighbouring job.
_ID_BYTES = 16


@dataclass(frozen=True, slots=True)
class JobKey:
    """The session a job is about. Also the key of the one-job lock."""

    season_year: int
    round_number: int
    session_type: SessionType


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    season_year: int
    round_number: int
    session_type: SessionType
    status: JobStatus
    stage: JobStage
    progress_percent: int | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    error_message: str | None
    rows_written: int | None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


def new_job_id() -> str:
    return secrets.token_urlsafe(_ID_BYTES)


def _for_key(key: JobKey) -> tuple[object, ...]:
    return (
        IngestionJob.season_year == key.season_year,
        IngestionJob.round_number == key.round_number,
        IngestionJob.session_type == key.session_type,
    )


async def is_ingested(connection: AsyncConnection, key: JobKey) -> bool:
    """Whether the session is stored whole, so a fetch would be wasted."""
    statement = (
        select(Session.ingested_at)
        .join(Meeting, Meeting.id == Session.meeting_id)
        .join(Season, Season.id == Meeting.season_id)
        .where(
            Season.year == key.season_year,
            Meeting.round_number == key.round_number,
            Session.session_type == key.session_type,
        )
    )
    return (await connection.execute(statement)).scalar_one_or_none() is not None


async def claim(connection: AsyncConnection, key: JobKey) -> str | None:
    """Create a pending job for the session, or None if one is already live."""
    job_id = new_job_id()
    statement = (
        insert(IngestionJob)
        .values(
            id=job_id,
            season_year=key.season_year,
            round_number=key.round_number,
            session_type=key.session_type,
            status=JobStatus.PENDING,
            stage=JobStage.RESOLVING,
        )
        # No conflict target: the only constraint a fresh random id can hit is
        # the partial unique index on live jobs for this session.
        .on_conflict_do_nothing()
        .returning(IngestionJob.id)
    )
    return (await connection.execute(statement)).scalar_one_or_none()


async def record_cached(connection: AsyncConnection, key: JobKey) -> str:
    """A job that finished before it began: the session was already stored.

    The caller still gets a job id, so the frontend has one code path whether
    or not a fetch was needed.
    """
    job_id = new_job_id()
    await connection.execute(
        insert(IngestionJob).values(
            id=job_id,
            season_year=key.season_year,
            round_number=key.round_number,
            session_type=key.session_type,
            status=JobStatus.SKIPPED_CACHED,
            stage=JobStage.VERIFYING,
            rows_written=0,
            started_at=func.now(),
            finished_at=func.now(),
        )
    )
    return job_id


async def find_active(connection: AsyncConnection, key: JobKey) -> str | None:
    statement = select(IngestionJob.id).where(
        *_for_key(key),  # type: ignore[arg-type]
        IngestionJob.status.in_(ACTIVE_STATUSES),
    )
    return (await connection.execute(statement)).scalar_one_or_none()


async def get(connection: AsyncConnection, job_id: str) -> JobRecord | None:
    row = (
        await connection.execute(select(IngestionJob.__table__).where(IngestionJob.id == job_id))
    ).first()
    if row is None:
        return None
    return JobRecord(
        id=row.id,
        season_year=row.season_year,
        round_number=row.round_number,
        session_type=SessionType(row.session_type),
        status=JobStatus(row.status),
        stage=JobStage(row.stage),
        progress_percent=row.progress_percent,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_message=row.error_message,
        rows_written=row.rows_written,
    )


async def start(connection: AsyncConnection, job_id: str) -> None:
    await connection.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id)
        .values(status=JobStatus.RUNNING, started_at=func.now())
    )


async def advance(connection: AsyncConnection, job_id: str, stage: JobStage) -> None:
    await connection.execute(
        update(IngestionJob).where(IngestionJob.id == job_id).values(stage=stage)
    )


async def finish(
    connection: AsyncConnection,
    job_id: str,
    status: JobStatus,
    *,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    await connection.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id)
        .values(
            status=status,
            rows_written=rows_written,
            error_message=error,
            finished_at=func.now(),
        )
    )
