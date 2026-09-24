"""Standings rows: the SQL behind the standings cache.

Every function takes a connection and leaves transactions to the caller. Rows
are keyed by `(season, round)`, so a refresh after a new race adds a round
rather than overwriting the last one; reads always take the latest round held.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import (
    Constructor,
    ConstructorStanding,
    Driver,
    DriverStanding,
    Season,
    StandingsFetch,
)
from app.ingestion.standings_provider import RawStandings


@dataclass(frozen=True, slots=True)
class FetchRecord:
    round_number: int
    fetched_at: dt.datetime


@dataclass(frozen=True, slots=True)
class DriverStandingRow:
    position: int | None
    driver_ref: str
    driver_name: str
    driver_code: str | None
    constructor_name: str | None
    points: float
    wins: int | None


@dataclass(frozen=True, slots=True)
class ConstructorStandingRow:
    position: int | None
    constructor_ref: str
    constructor_name: str
    points: float
    wins: int | None


async def latest_fetch(connection: AsyncConnection, season: int) -> FetchRecord | None:
    statement = (
        select(StandingsFetch.round_number, StandingsFetch.fetched_at)
        .join(Season, Season.id == StandingsFetch.season_id)
        .where(Season.year == season)
        .order_by(StandingsFetch.fetched_at.desc())
        .limit(1)
    )
    row = (await connection.execute(statement)).first()
    return FetchRecord(row.round_number, row.fetched_at) if row else None


async def _ids_by_ref(
    connection: AsyncConnection, table: Any, ref_column: str, rows: dict[str, dict[str, Any]]
) -> dict[str, int]:
    """Ensure each row exists and return ref -> id, without overwriting details.

    `DO UPDATE` sets only the key to itself: `DO NOTHING` would return no id
    for an existing row. Ingestion owns the descriptive columns, since FastF1
    is the richer source for them.
    """
    if not rows:
        return {}
    base = insert(table).values(list(rows.values()))
    statement = base.on_conflict_do_update(
        index_elements=[ref_column], set_={ref_column: base.excluded[ref_column]}
    ).returning(getattr(table, ref_column), table.id)
    return {ref: int(row_id) for ref, row_id in (await connection.execute(statement)).all()}


async def save(connection: AsyncConnection, raw: RawStandings) -> None:
    base = insert(Season).values(year=raw.season)
    season_id = (
        await connection.execute(
            base.on_conflict_do_update(
                index_elements=["year"], set_={"year": base.excluded.year}
            ).returning(Season.id)
        )
    ).scalar_one()

    teams: dict[str, dict[str, Any]] = {
        c.constructor_ref: {
            "constructor_ref": c.constructor_ref,
            "name": c.name,
            "nationality": c.nationality,
        }
        for c in raw.constructors
    }
    for d in raw.drivers:
        if d.constructor_ref and d.constructor_ref not in teams:
            # Same keys as above: a multi-row insert needs a uniform shape.
            teams[d.constructor_ref] = {
                "constructor_ref": d.constructor_ref,
                "name": d.constructor_name or d.constructor_ref,
                "nationality": None,
            }
    team_ids = await _ids_by_ref(connection, Constructor, "constructor_ref", teams)

    people = {
        d.driver_ref: {
            "driver_ref": d.driver_ref,
            "driver_code": d.code,
            "first_name": d.first_name,
            "last_name": d.last_name,
            "full_name": d.full_name,
            "nationality": d.nationality,
            "permanent_number": d.permanent_number,
        }
        for d in raw.drivers
    }
    driver_ids = await _ids_by_ref(connection, Driver, "driver_ref", people)

    if raw.drivers:
        rows = [
            {
                "season_id": season_id,
                "round_number": raw.round_number,
                "driver_id": driver_ids[d.driver_ref],
                "constructor_id": team_ids.get(d.constructor_ref or ""),
                "position": d.position,
                "points": d.points,
                "wins": d.wins,
            }
            for d in raw.drivers
        ]
        await _upsert_standings(
            connection, DriverStanding, rows, "driver_id", extra=("constructor_id",)
        )

    if raw.constructors:
        rows = [
            {
                "season_id": season_id,
                "round_number": raw.round_number,
                "constructor_id": team_ids[c.constructor_ref],
                "position": c.position,
                "points": c.points,
                "wins": c.wins,
            }
            for c in raw.constructors
        ]
        await _upsert_standings(connection, ConstructorStanding, rows, "constructor_id")

    fetch = insert(StandingsFetch).values(
        season_id=season_id, round_number=raw.round_number, source="jolpica"
    )
    await connection.execute(
        fetch.on_conflict_do_update(
            index_elements=["season_id", "round_number"], set_={"fetched_at": func.now()}
        )
    )


async def _upsert_standings(
    connection: AsyncConnection,
    table: Any,
    rows: list[dict[str, Any]],
    entity_column: str,
    extra: tuple[str, ...] = (),
) -> None:
    base = insert(table).values(rows)
    updates = {column: base.excluded[column] for column in ("position", "points", "wins", *extra)}
    await connection.execute(
        base.on_conflict_do_update(
            index_elements=["season_id", "round_number", entity_column],
            set_={**updates, "fetched_at": func.now()},
        )
    )


def _latest_round(table: Any, season: int) -> Any:
    return (
        select(func.max(table.round_number))
        .join(Season, Season.id == table.season_id)
        .where(Season.year == season)
        .scalar_subquery()
    )


async def read_drivers(connection: AsyncConnection, season: int) -> list[DriverStandingRow]:
    statement = (
        select(
            DriverStanding.position,
            Driver.driver_ref,
            Driver.full_name,
            Driver.driver_code,
            Constructor.name.label("constructor_name"),
            DriverStanding.points,
            DriverStanding.wins,
        )
        .join(Season, Season.id == DriverStanding.season_id)
        .join(Driver, Driver.id == DriverStanding.driver_id)
        .outerjoin(Constructor, Constructor.id == DriverStanding.constructor_id)
        .where(Season.year == season)
        .where(DriverStanding.round_number == _latest_round(DriverStanding, season))
        .order_by(DriverStanding.position.asc().nulls_last(), DriverStanding.points.desc())
    )
    return [
        DriverStandingRow(
            position=row.position,
            driver_ref=row.driver_ref,
            driver_name=row.full_name,
            driver_code=row.driver_code,
            constructor_name=row.constructor_name,
            points=float(row.points),
            wins=row.wins,
        )
        for row in (await connection.execute(statement)).all()
    ]


async def read_constructors(
    connection: AsyncConnection, season: int
) -> list[ConstructorStandingRow]:
    statement = (
        select(
            ConstructorStanding.position,
            Constructor.constructor_ref,
            Constructor.name,
            ConstructorStanding.points,
            ConstructorStanding.wins,
        )
        .join(Season, Season.id == ConstructorStanding.season_id)
        .join(Constructor, Constructor.id == ConstructorStanding.constructor_id)
        .where(Season.year == season)
        .where(ConstructorStanding.round_number == _latest_round(ConstructorStanding, season))
        .order_by(
            ConstructorStanding.position.asc().nulls_last(), ConstructorStanding.points.desc()
        )
    )
    return [
        ConstructorStandingRow(
            position=row.position,
            constructor_ref=row.constructor_ref,
            constructor_name=row.name,
            points=float(row.points),
            wins=row.wins,
        )
        for row in (await connection.execute(statement)).all()
    ]
