"""Response models for the race endpoints.

These mirror `frontend/lib/api/types.ts` field for field. The frontend is
already written and tested against those shapes, so a rename here is a silent
break: the UI simply renders an empty state instead of an error.

Durations cross the wire as **formatted strings** (`"1:23.456"`), not
milliseconds, because that is what the frontend renders directly. Lap traces
are the exception — those are numbers, since they are plotted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.api.schemas.common import iso, race_id
from app.api.schemas.report import ReportOut
from app.db.models.enums import SessionType

IngestionState = Literal["ingested", "available", "upcoming"]


def format_lap_time(milliseconds: int | None) -> str | None:
    """Milliseconds as a driver would read them: `1:23.456`, or `23.456`.

    Minutes are dropped below a minute, which is how timing screens show
    sector times and pit stops.
    """
    if milliseconds is None or milliseconds < 0:
        return None
    total_seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes}:{seconds:02d}.{millis:03d}"
    return f"{seconds}.{millis:03d}"


def format_gap(milliseconds: int | None) -> str | None:
    """A gap to the leader, as `+1.234` or `+1:02.345`."""
    formatted = format_lap_time(milliseconds)
    return None if formatted is None else f"+{formatted}"


class CalendarRound(BaseModel):
    season: int
    round: int
    event_name: str
    circuit_name: str
    country: str | None
    event_date: str
    state: IngestionState
    total_laps: int | None


class RaceSummary(BaseModel):
    id: str
    season: int
    round: int
    event_name: str
    circuit_name: str
    event_date: str
    state: IngestionState
    winner_name: str | None
    has_report: bool


class RaceDetail(RaceSummary):
    total_laps: int | None
    fastest_lap_time: str | None
    fastest_lap_driver: str | None
    safety_car_periods: int | None
    winning_margin: str | None


class ClassificationRow(BaseModel):
    position: int
    driver_name: str
    driver_code: str
    constructor_name: str
    grid_position: int | None
    points: float
    status: str
    best_lap_time: str | None
    pit_stop_count: int | None
    gap_to_leader: str | None


class PositionChange(BaseModel):
    driver_name: str
    driver_code: str
    grid_position: int
    finish_position: int
    positions_gained: int


class LapPacePoint(BaseModel):
    lap_number: int
    lap_time_ms: int


class DriverPaceTrace(BaseModel):
    driver_code: str
    driver_name: str
    laps: list[LapPacePoint]


class TyreStint(BaseModel):
    compound: str
    start_lap: int
    end_lap: int


class DriverStrategy(BaseModel):
    driver_name: str
    driver_code: str
    stop_count: int
    stints: list[TyreStint]


class PitStopRow(BaseModel):
    driver_name: str
    driver_code: str
    lap: int
    duration_seconds: float


class RaceControlEventOut(BaseModel):
    lap: int | None
    event_type: str
    message: str
    timestamp: str | None


class RaceStats(BaseModel):
    classification: list[ClassificationRow]
    position_changes: list[PositionChange]
    pace_traces: list[DriverPaceTrace]
    strategies: list[DriverStrategy]
    pit_stops: list[PitStopRow]
    race_control: list[RaceControlEventOut]


class DashboardSummary(BaseModel):
    season: int
    rounds_ingested: int
    rounds_on_calendar: int
    laps_stored: int
    reports_written: int
    average_cold_fetch_seconds: float | None
    latest_race: RaceSummary | None
    latest_podium: list[ClassificationRow]
    latest_report: ReportOut | None = None


__all__ = [
    "CalendarRound",
    "ClassificationRow",
    "DashboardSummary",
    "DriverPaceTrace",
    "DriverStrategy",
    "IngestionState",
    "LapPacePoint",
    "PitStopRow",
    "PositionChange",
    "RaceControlEventOut",
    "RaceDetail",
    "RaceStats",
    "RaceSummary",
    "SessionType",
    "TyreStint",
    "format_gap",
    "format_lap_time",
    "iso",
    "race_id",
]
