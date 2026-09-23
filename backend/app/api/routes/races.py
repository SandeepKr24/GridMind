"""Race endpoints.

Paths match `frontend/lib/api/races.ts` exactly. Every read runs on the
read-only connection.

Race ids are `{season}-{round}`, e.g. `2024-14`. The frontend builds them and
passes them back, so they are parsed defensively: anything that is not two
plausible integers is a 404, not a 500.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request

from app.analytics import race_stats
from app.api.schemas.race import (
    CalendarRound,
    DashboardSummary,
    RaceDetail,
    RaceStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["races"])

RACE_ID = re.compile(r"^(\d{4})-(\d{1,2})$")

# FastF1's timing coverage starts in 2018; the frontend's season picker agrees.
FIRST_SEASON = 2018
LAST_SEASON = 2100


def parse_race_id(raw: str) -> tuple[int, int]:
    """`2024-14` to `(2024, 14)`, or a 404.

    A malformed id is a bad URL, not a server fault, so it must not reach the
    query layer.
    """
    match = RACE_ID.match(raw)
    if match is None:
        raise HTTPException(status_code=404, detail="Unknown race")
    season, round_number = int(match.group(1)), int(match.group(2))
    if not FIRST_SEASON <= season <= LAST_SEASON or round_number < 1:
        raise HTTPException(status_code=404, detail="Unknown race")
    return season, round_number


@router.get("/seasons/{season}/calendar", response_model=list[CalendarRound])
async def calendar(season: int, request: Request) -> list[CalendarRound]:
    """Rounds we hold for a season.

    An empty list is a valid answer, not an error: the database starts empty
    and fills as people ask questions.
    """
    async with request.app.state.database.connect(read_only=True) as connection:
        return await race_stats.get_calendar(connection, season)


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(request: Request, season: int = Query(...)) -> DashboardSummary:
    async with request.app.state.database.connect(read_only=True) as connection:
        data = await race_stats.get_dashboard(connection, season)

    return DashboardSummary(
        season=data.season,
        rounds_ingested=data.rounds_ingested,
        rounds_on_calendar=data.rounds_on_calendar,
        laps_stored=data.laps_stored,
        # Reports are not implemented yet. Zero is the truth, not a placeholder.
        reports_written=0,
        average_cold_fetch_seconds=None,
        latest_race=data.latest_race,
        latest_podium=data.latest_podium,
    )


@router.get("/races/{race}", response_model=RaceDetail)
async def race_detail(race: str, request: Request) -> RaceDetail:
    season, round_number = parse_race_id(race)
    async with request.app.state.database.connect(read_only=True) as connection:
        detail = await race_stats.get_race(connection, season, round_number)
    if detail is None:
        raise HTTPException(status_code=404, detail="Race not stored")
    return detail


@router.get("/races/{race}/stats", response_model=RaceStats)
async def race_statistics(race: str, request: Request) -> RaceStats:
    season, round_number = parse_race_id(race)
    async with request.app.state.database.connect(read_only=True) as connection:
        stats = await race_stats.get_race_stats(connection, season, round_number)
    if stats is None:
        raise HTTPException(status_code=404, detail="Race not stored")
    return stats
