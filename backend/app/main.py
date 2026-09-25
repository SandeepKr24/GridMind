"""Application factory.

`create_app` takes its settings and database as arguments so tests can build a
fully wired app without a live Postgres, and so nothing is constructed at
import time.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, jobs, races
from app.api.routes import standings as standings_routes
from app.config import Settings
from app.db.database import Database
from app.ingestion.fastf1_provider import FastF1Provider
from app.ingestion.runner import JobRunner, PostgresJobStore
from app.ingestion.schedule import ScheduleCache, ScheduleSource
from app.ingestion.standings_provider import JolpicaClient
from app.ingestion.standings_service import PostgresStandingsStore, StandingsService
from app.llm import LLMProvider, build_llm
from app.runtime import configure_event_loop

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    schedules: ScheduleSource | None = None,
    runner: JobRunner | None = None,
    standings: StandingsService | None = None,
    llm: LLMProvider | None = None,
) -> FastAPI:
    # Must happen before the first connection is opened; no-op off Windows.
    configure_event_loop()
    settings = settings or Settings()  # type: ignore[call-arg]
    db = database if database is not None else Database(settings)
    provider = FastF1Provider(settings.fastf1_cache_dir)
    calendar = schedules or ScheduleCache(
        provider, ttl=dt.timedelta(hours=settings.schedule_cache_ttl_hours)
    )
    ingestion = runner or JobRunner(
        PostgresJobStore(db),
        provider,
        max_concurrent=settings.max_concurrent_ingestion_jobs,
        max_pending=settings.max_pending_ingestion_jobs,
        timeout_seconds=settings.ingestion_job_timeout_seconds,
    )
    championship = standings or StandingsService(
        PostgresStandingsStore(db),
        JolpicaClient(settings.jolpica_base_url),
        ttl=dt.timedelta(hours=settings.standings_cache_ttl_hours),
    )
    # None when no key is configured; only chat depends on it.
    language_model = llm or build_llm(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.database = db
        app.state.schedules = calendar
        app.state.runner = ingestion
        app.state.standings = championship
        app.state.llm = language_model
        yield
        # Cancelled jobs keep live rows; the next process fails them as orphans.
        await ingestion.shutdown()
        # Connections left open delay Neon's suspend, which costs compute time.
        await db.dispose()

    app = FastAPI(
        title="GridMind API",
        description="AI-powered F1 race analyst.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(health.router)
    app.include_router(races.router)
    app.include_router(jobs.router)
    app.include_router(standings_routes.router)
    return app
