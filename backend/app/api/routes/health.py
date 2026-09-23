"""Liveness and readiness.

Kept apart because they answer different questions and have different costs.
`/health` says the process is up and must stay free of database work; see the
note in `app.db.database.Database.ping`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    """Is the process alive? No database call — deliberately."""
    return {"status": "ok"}


@router.get("/health/db")
async def readiness(request: Request) -> JSONResponse:
    """Can we reach Postgres? Call this deliberately, not on a poll."""
    database = request.app.state.database
    try:
        await database.ping()
    except Exception:
        # Logged with detail, reported without: driver errors name the host and
        # role, and this API is public.
        logger.exception("readiness check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
