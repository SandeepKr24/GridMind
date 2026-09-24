"""The standings cache: when to call jolpica-f1, and what to serve when we can't.

    fresh in Postgres  -> serve it, no call
    stale or missing   -> one call (drivers + constructors), store, serve
    call fails         -> serve the stale rows marked stale, or fail if none

"Fresh" depends on the season. A past season fetched after its year ended is
final and never fetched again. Anything else — the current season, or a past
one we last saw mid-season — is refreshed once `ttl` has passed, since
standings only move after a race weekend.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.db.database import Database
from app.ingestion import standings_store as sql
from app.ingestion.standings_provider import RawStandings, StandingsUnavailableError
from app.ingestion.standings_store import (
    ConstructorStandingRow,
    DriverStandingRow,
    FetchRecord,
)

logger = logging.getLogger(__name__)

#: The first world championship season.
FIRST_CHAMPIONSHIP = 1950


class SeasonOutOfRangeError(ValueError):
    """No championship exists for this season."""


@dataclass(frozen=True, slots=True)
class StandingsResult[Row]:
    season: int
    #: The round these standings are after; None before the first race.
    round_number: int | None
    fetched_at: dt.datetime | None
    #: True when the refresh failed and older standings are being served.
    is_stale: bool
    rows: list[Row]


class StandingsStore(Protocol):
    async def latest_fetch(self, season: int) -> FetchRecord | None: ...
    async def save(self, raw: RawStandings) -> None: ...
    async def read_drivers(self, season: int) -> list[DriverStandingRow]: ...
    async def read_constructors(self, season: int) -> list[ConstructorStandingRow]: ...


class StandingsSource(Protocol):
    async def fetch(self, season: int) -> RawStandings: ...


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class StandingsService:
    def __init__(
        self,
        store: StandingsStore,
        client: StandingsSource,
        *,
        ttl: dt.timedelta,
        now: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._client = client
        self._ttl = ttl
        self._now = now
        self._locks: dict[int, asyncio.Lock] = {}

    async def drivers(self, season: int) -> StandingsResult[DriverStandingRow]:
        fetch, stale = await self._ensure_fresh(season)
        return self._result(season, fetch, stale, await self._store.read_drivers(season))

    async def constructors(self, season: int) -> StandingsResult[ConstructorStandingRow]:
        fetch, stale = await self._ensure_fresh(season)
        return self._result(season, fetch, stale, await self._store.read_constructors(season))

    @staticmethod
    def _result[Row](
        season: int, fetch: FetchRecord | None, stale: bool, rows: list[Row]
    ) -> StandingsResult[Row]:
        return StandingsResult(
            season=season,
            round_number=fetch.round_number if fetch and fetch.round_number > 0 else None,
            fetched_at=fetch.fetched_at if fetch else None,
            is_stale=stale,
            rows=rows,
        )

    def _is_fresh(self, season: int, fetch: FetchRecord | None) -> bool:
        if fetch is None:
            return False
        if fetch.fetched_at.year > season:
            return True
        return self._now() - fetch.fetched_at < self._ttl

    async def _ensure_fresh(self, season: int) -> tuple[FetchRecord | None, bool]:
        if not FIRST_CHAMPIONSHIP <= season <= self._now().year:
            raise SeasonOutOfRangeError(f"no championship for {season}")

        fetch = await self._store.latest_fetch(season)
        if self._is_fresh(season, fetch):
            return fetch, False

        # One refresh per season at a time: jolpica is rate-limited, and a
        # burst of requests on a stale season must cost one call, not one each.
        async with self._locks.setdefault(season, asyncio.Lock()):
            fetch = await self._store.latest_fetch(season)
            if self._is_fresh(season, fetch):
                return fetch, False
            try:
                await self._store.save(await self._client.fetch(season))
            except StandingsUnavailableError as error:
                if fetch is None:
                    raise
                logger.warning("standings %s: refresh failed (%s); serving stale", season, error)
                return fetch, True
            return await self._store.latest_fetch(season), False


class PostgresStandingsStore:
    """`StandingsStore` on the writer engine. Saves are one transaction."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def latest_fetch(self, season: int) -> FetchRecord | None:
        async with self._db.connect(read_only=True) as connection:
            return await sql.latest_fetch(connection, season)

    async def save(self, raw: RawStandings) -> None:
        async with self._db.writer.begin() as connection:
            await sql.save(connection, raw)

    async def read_drivers(self, season: int) -> list[DriverStandingRow]:
        async with self._db.connect(read_only=True) as connection:
            return await sql.read_drivers(connection, season)

    async def read_constructors(self, season: int) -> list[ConstructorStandingRow]:
        async with self._db.connect(read_only=True) as connection:
            return await sql.read_constructors(connection, season)
