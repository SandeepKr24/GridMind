"""Async engines for the two database roles.

GridMind connects as two different Postgres roles on purpose:

* the **writer** (`neondb_owner`) runs migrations and ingestion;
* the **reader** (`gridmind_readonly`) runs the SQL the agent generates, and is
  restricted to SELECT by database grants rather than by application code.

Both point at Neon's direct endpoint. The pooled one would break psycopg's
prepared statements and silently discard the session-level `search_path` set
below; `Settings` refuses a `-pooler` host for exactly that reason.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings

logger = logging.getLogger(__name__)

# Neon closes idle connections when the compute suspends after ~5 minutes, so
# recycling sooner than that keeps us from handing out a doomed connection.
POOL_RECYCLE_SECONDS = 240

# One container, modest traffic. A larger pool would not add throughput, and
# every extra connection is one more thing to re-establish after a resume.
POOL_SIZE = 5
MAX_OVERFLOW = 5

# A query that has not finished in this long is a bug, not a slow query.
WRITER_STATEMENT_TIMEOUT_MS = 30_000

# An open transaction is the one thing that genuinely holds a Neon compute
# awake, so neither role is allowed to sit in one.
IDLE_IN_TRANSACTION_TIMEOUT_MS = 30_000


def _server_settings(settings: Settings, *, read_only: bool) -> dict[str, str]:
    options = {
        "search_path": settings.database_schema,
        "idle_in_transaction_session_timeout": str(IDLE_IN_TRANSACTION_TIMEOUT_MS),
    }
    if read_only:
        # Belt and braces. The grants already prevent writes; this makes the
        # refusal happen before the statement reaches a table, and covers
        # anything we might accidentally grant later.
        options["default_transaction_read_only"] = "on"
    else:
        options["statement_timeout"] = str(WRITER_STATEMENT_TIMEOUT_MS)
    return options


def build_connect_args(settings: Settings, *, read_only: bool) -> dict[str, str]:
    """The `connect_args` handed to the engine, as a value we can assert on.

    SQLAlchemy keeps `connect_args` inside a closure once the engine exists, so
    building them here is what makes them testable.
    """
    return {"options": _pg_options(_server_settings(settings, read_only=read_only))}


def _create_engine(url: str, settings: Settings, *, read_only: bool) -> AsyncEngine:
    return create_async_engine(
        url,
        # Required, not optional: Neon closing an idle connection at suspend is
        # normal. Without pre-ping the first query after a resume fails.
        pool_pre_ping=True,
        pool_recycle=POOL_RECYCLE_SECONDS,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        connect_args=build_connect_args(settings, read_only=read_only),
    )


def _pg_options(server_settings: dict[str, str]) -> str:
    """Render libpq's `options` string: `-c key=value` pairs."""
    return " ".join(f"-c {key}={value}" for key, value in server_settings.items())


class Database:
    """Owns both engines and their lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.writer: AsyncEngine = _create_engine(settings.database_url, settings, read_only=False)
        self.reader: AsyncEngine = _create_engine(
            settings.database_url_readonly, settings, read_only=True
        )

    @asynccontextmanager
    async def connect(self, *, read_only: bool = False) -> AsyncIterator[AsyncConnection]:
        engine = self.reader if read_only else self.writer
        async with engine.connect() as connection:
            yield connection

    async def ping(self) -> bool:
        """Readiness check. Raises if the database cannot be reached.

        Deliberately not called by the liveness endpoint: every query resets
        Neon's scale-to-zero timer, so a polled database check would keep the
        compute awake around the clock.
        """
        async with self.writer.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    async def dispose(self) -> None:
        await self.writer.dispose()
        await self.reader.dispose()
