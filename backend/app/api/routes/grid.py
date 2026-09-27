"""The current grid, for the drivers and teams pages.

Read from OpenF1's latest race through an in-memory cache; never touches the
database, so it works however little has been ingested.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas.grid import GridOut
from app.ingestion.grid import GridUnavailableError

router = APIRouter(prefix="/api", tags=["grid"])

RETRY_AFTER_SECONDS = 300


@router.get("/grid", response_model=GridOut)
async def current_grid(request: Request) -> GridOut:
    try:
        result = await request.app.state.grid.get()
    except GridUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="The current grid is unavailable right now. Try again later.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        ) from error
    return GridOut.from_result(result)
