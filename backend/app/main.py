"""Application factory.

`create_app` takes its settings and database as arguments so tests can build a
fully wired app without a live Postgres, and so nothing is constructed at
import time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.config import Settings
from app.db.database import Database
from app.runtime import configure_event_loop

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    # Must happen before the first connection is opened; no-op off Windows.
    configure_event_loop()
    settings = settings or Settings()  # type: ignore[call-arg]
    db = database if database is not None else Database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.database = db
        yield
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
    return app
