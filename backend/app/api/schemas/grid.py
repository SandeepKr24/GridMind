"""Wire models for the current grid. Mirrors `CurrentGrid` in frontend/lib/api/types.ts."""

from __future__ import annotations

from pydantic import BaseModel

from app.api.schemas.race import iso
from app.ingestion.grid import GridResult


class GridDriverOut(BaseModel):
    number: int
    code: str
    first_name: str
    last_name: str
    team_name: str
    team_colour: str | None
    headshot_url: str | None


class GridOut(BaseModel):
    season: int
    race_location: str
    race_date: str
    fetched_at: str | None
    is_stale: bool
    drivers: list[GridDriverOut]

    @classmethod
    def from_result(cls, result: GridResult) -> GridOut:
        grid = result.grid
        return cls(
            season=grid.season,
            race_location=grid.race_location,
            race_date=grid.race_date.isoformat(),
            fetched_at=iso(result.fetched_at),
            is_stale=result.is_stale,
            drivers=[
                GridDriverOut(
                    number=d.number,
                    code=d.code,
                    first_name=d.first_name,
                    last_name=d.last_name,
                    team_name=d.team_name,
                    team_colour=d.team_colour,
                    headshot_url=d.headshot_url,
                )
                for d in grid.drivers
            ],
        )
