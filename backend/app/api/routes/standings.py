"""Championship standings, via the jolpica-f1 cache.

Season-level questions cannot come from ingested sessions (we hold only the
ones somebody asked about), so these endpoints never touch timing data.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas.race import iso
from app.api.schemas.standings import ConstructorStandingsOut, DriverStandingsOut
from app.ingestion.standings_provider import StandingsUnavailableError
from app.ingestion.standings_service import SeasonOutOfRangeError, StandingsResult

router = APIRouter(prefix="/api/standings", tags=["standings"])

RETRY_AFTER_SECONDS = 300


async def _resolve[T](pending: Awaitable[StandingsResult[T]]) -> dict[str, Any]:
    try:
        result = await pending
    except SeasonOutOfRangeError as error:
        raise HTTPException(status_code=404, detail="No championship for that season") from error
    except StandingsUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="Standings are unavailable right now. Try again later.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        ) from error
    return {
        "season": result.season,
        "round": result.round_number,
        "fetched_at": iso(result.fetched_at),
        "is_stale": result.is_stale,
        "standings": [dataclasses.asdict(row) for row in result.rows],  # type: ignore[call-overload]
    }


@router.get("/{year}/drivers", response_model=DriverStandingsOut)
async def driver_standings(year: int, request: Request) -> DriverStandingsOut:
    body = await _resolve(request.app.state.standings.drivers(year))
    return DriverStandingsOut.model_validate(body)


@router.get("/{year}/constructors", response_model=ConstructorStandingsOut)
async def constructor_standings(year: int, request: Request) -> ConstructorStandingsOut:
    body = await _resolve(request.app.state.standings.constructors(year))
    return ConstructorStandingsOut.model_validate(body)
