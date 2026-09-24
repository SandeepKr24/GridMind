"""Wire models for championship standings."""

from __future__ import annotations

from pydantic import BaseModel


class DriverStandingOut(BaseModel):
    #: None for a driver excluded from the championship.
    position: int | None
    driver_ref: str
    driver_name: str
    driver_code: str | None
    constructor_name: str | None
    points: float
    wins: int | None


class ConstructorStandingOut(BaseModel):
    position: int | None
    constructor_ref: str
    constructor_name: str
    points: float
    wins: int | None


class StandingsMeta(BaseModel):
    season: int
    #: The round these standings are after; null before the first race.
    round: int | None
    fetched_at: str | None
    #: The refresh failed and these are older standings. Say so, don't hide it.
    is_stale: bool


class DriverStandingsOut(StandingsMeta):
    standings: list[DriverStandingOut]


class ConstructorStandingsOut(StandingsMeta):
    standings: list[ConstructorStandingOut]
