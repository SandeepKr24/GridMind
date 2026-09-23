"""Ingestion jobs — the table that makes on-demand fetching safe to observe.

A job row is what the Loading Pit polls, and it is also the lock. The partial
unique index below is the part that matters: it lets Postgres, rather than
application code, guarantee that two people asking about the same session at
the same time cannot start two ingestions of it.

The job is keyed by `(season_year, round_number, session_type)` — the natural
identifiers — rather than by `session_id`, because the job may be created
before the session row exists.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, pg_enum
from app.db.models.enums import JobStage, JobStatus, SessionType


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        # The concurrency guard. Partial, so it constrains only live jobs:
        # any number of finished jobs for the same session may pile up as
        # history, but at most one may be pending or running.
        #
        # It must list the same literals as `ACTIVE_STATUSES`; there is a test
        # that fails if the two drift apart.
        Index(
            "uq_ingestion_jobs_active",
            "season_year",
            "round_number",
            "session_type",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index(
            "ix_ingestion_jobs_season_year_round_number_session_type",
            "season_year",
            "round_number",
            "session_type",
        ),
    )

    # A public identifier, not a sequence. It travels in the URL as `?job=`,
    # and the frontend validates it against ^[A-Za-z0-9_-]{1,64}$.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    season_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    session_type: Mapped[SessionType] = mapped_column(
        pg_enum(SessionType, "session_type"), nullable=False
    )

    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    stage: Mapped[JobStage] = mapped_column(
        pg_enum(JobStage, "job_stage"),
        nullable=False,
        default=JobStage.RESOLVING,
    )
    progress_percent: Mapped[int | None] = mapped_column(SmallInteger)

    # The frontend measures elapsed time from `started_at`, so that a refresh
    # mid-ingest still shows a truthful timer.
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    error_message: Mapped[str | None] = mapped_column(Text)
    rows_written: Mapped[int | None] = mapped_column(Integer)

    # Conversations are held in memory and forgotten on restart, so this is a
    # loose reference for debugging, not a foreign key.
    requested_by_conversation_id: Mapped[str | None] = mapped_column(String(64))
