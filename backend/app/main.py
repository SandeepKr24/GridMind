"""Application factory.

`create_app` takes its settings and database as arguments so tests can build a
fully wired app without a live Postgres, and so nothing is constructed at
import time.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.conversations import ConversationStore
from app.agent.entity_resolver import EntityResolver
from app.agent.executor import PostgresQueryRunner
from app.agent.ingestion_gate import IngestionGate
from app.agent.orchestrator import ChatAgent
from app.agent.session_context import PostgresSessionDirectory
from app.agent.sql_agent import SqlAgent
from app.api.rate_limit import build_rate_limits
from app.api.routes import chat as chat_routes
from app.api.routes import health, jobs, races
from app.api.routes import reports as report_routes
from app.api.routes import standings as standings_routes
from app.config import Settings
from app.db.database import Database
from app.ingestion.fastf1_provider import FastF1Provider
from app.ingestion.runner import JobRunner, PostgresJobStore
from app.ingestion.schedule import ScheduleCache, ScheduleSource
from app.ingestion.standings_provider import JolpicaClient
from app.ingestion.standings_service import PostgresStandingsStore, StandingsService
from app.llm import LLMProvider, build_llm
from app.reports.jobs import ReportJobs
from app.reports.scheduler import AutoReporter
from app.reports.store import PostgresFactsSource, PostgresReportArchive
from app.runtime import configure_event_loop

logger = logging.getLogger(__name__)


def build_chat_agent(
    llm: LLMProvider,
    db: Database,
    calendar: ScheduleSource,
    runner: JobRunner,
    standings: StandingsService,
    settings: Settings,
) -> ChatAgent:
    return ChatAgent(
        llm,
        EntityResolver(llm, calendar),
        IngestionGate(runner, max_sessions=settings.max_sessions_per_question),
        SqlAgent(llm, PostgresSessionDirectory(db), PostgresQueryRunner(db)),
        standings,
    )


def _start_auto_reports(
    settings: Settings,
    calendar: ScheduleSource,
    report_jobs: ReportJobs | None,
    db: Database,
) -> asyncio.Task[None] | None:
    """The post-race report loop, or None when disabled or without an LLM."""
    if not settings.auto_report_enabled or report_jobs is None:
        return None
    reporter = AutoReporter(
        calendar,
        report_jobs,
        PostgresReportArchive(db),
        window_days=settings.auto_report_window_days,
    )
    interval = dt.timedelta(hours=settings.auto_report_check_hours)
    return asyncio.create_task(reporter.run(interval), name="auto-reports")


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    schedules: ScheduleSource | None = None,
    runner: JobRunner | None = None,
    standings: StandingsService | None = None,
    llm: LLMProvider | None = None,
    chat: ChatAgent | None = None,
    reports: ReportJobs | None = None,
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
    chat_agent = chat
    if chat_agent is None and language_model is not None:
        chat_agent = build_chat_agent(
            language_model, db, calendar, ingestion, championship, settings
        )
    report_jobs = reports
    if report_jobs is None and language_model is not None:
        report_jobs = ReportJobs(
            language_model,
            ingestion,
            PostgresFactsSource(db),
            PostgresReportArchive(db),
            timeout_seconds=settings.ingestion_job_timeout_seconds + 300,
        )
    conversations = ConversationStore(
        ttl=dt.timedelta(minutes=settings.conversation_ttl_minutes),
        max_conversations=settings.max_conversations_in_memory,
    )
    rate_limits = build_rate_limits(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.database = db
        app.state.schedules = calendar
        app.state.runner = ingestion
        app.state.standings = championship
        app.state.llm = language_model
        app.state.chat = chat_agent
        app.state.conversations = conversations
        app.state.reports = report_jobs
        app.state.rate_limits = rate_limits
        auto_reports = _start_auto_reports(settings, calendar, report_jobs, db)
        app.state.auto_reports = auto_reports
        yield
        if auto_reports is not None:
            auto_reports.cancel()
            await asyncio.gather(auto_reports, return_exceptions=True)
        if report_jobs is not None:
            await report_jobs.shutdown()
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
    app.include_router(chat_routes.router)
    app.include_router(report_routes.router)
    return app
