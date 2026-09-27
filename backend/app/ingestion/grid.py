"""The current grid: who raced in the latest Grand Prix, from OpenF1.

The drivers and teams pages list the grid as it is now, and it changes during a
season (a driver swapped between sister teams, a stand-in for an injured one).
The latest *race* is the truth for that; practice sessions are not, because
teams run rookies in them.

OpenF1 also publishes each driver's official headshot URL on Formula 1's media
server, which the pages show. Everything read from OpenF1 is untrusted: rows
without a name are dropped, headshots are kept only on F1's own media host, and
team colours only as six hex digits.

One refresh is two requests (the season's races, then that race's drivers).
`GridCache` holds the result for hours and serves the last good copy, flagged
stale, when OpenF1 is down.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
HEADSHOT_HOST = "https://media.formula1.com/"
#: OpenF1 links the 93px rendition; the same path serves a 206px one.
_SMALL_HEADSHOT = "/1col/"
_LARGE_HEADSHOT = "/2col/"
_HEX_COLOUR = re.compile(r"^[0-9A-Fa-f]{6}$")


class GridUnavailableError(RuntimeError):
    """OpenF1 could not supply the current grid, and nothing is cached."""


@dataclass(frozen=True, slots=True)
class GridDriver:
    number: int
    code: str
    first_name: str
    last_name: str
    team_name: str
    #: "#RRGGBB", or None when OpenF1 sent nothing usable.
    team_colour: str | None
    headshot_url: str | None


@dataclass(frozen=True, slots=True)
class Grid:
    season: int
    #: Where the race the grid was read from took place, e.g. "Baku".
    race_location: str
    race_date: dt.date
    drivers: tuple[GridDriver, ...]


@dataclass(frozen=True, slots=True)
class GridResult:
    grid: Grid
    fetched_at: dt.datetime
    #: True when this is an older copy served because a refresh failed.
    is_stale: bool


def _headshot(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith(HEADSHOT_HOST):
        return None
    return value.replace(_SMALL_HEADSHOT, _LARGE_HEADSHOT, 1)


def _colour(value: Any) -> str | None:
    if isinstance(value, str) and _HEX_COLOUR.match(value):
        return f"#{value.upper()}"
    return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_drivers(rows: Any) -> tuple[GridDriver, ...]:
    """OpenF1 `/drivers` rows to grid drivers, dropping unusable rows."""
    if not isinstance(rows, list):
        raise GridUnavailableError("drivers response is not a list")
    drivers: dict[int, GridDriver] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = row.get("driver_number")
        code = _text(row.get("name_acronym")).upper()
        first, last = _text(row.get("first_name")), _text(row.get("last_name"))
        team = _text(row.get("team_name"))
        if not isinstance(number, int) or not code or not last or not team:
            continue
        drivers[number] = GridDriver(
            number=number,
            code=code,
            first_name=first,
            last_name=last,
            team_name=team,
            team_colour=_colour(row.get("team_colour")),
            headshot_url=_headshot(row.get("headshot_url")),
        )
    if not drivers:
        raise GridUnavailableError("the latest race lists no usable drivers")
    return tuple(sorted(drivers.values(), key=lambda d: d.number))


def latest_race(sessions: Any, now: dt.datetime) -> dict[str, Any] | None:
    """The most recent finished, not cancelled race among OpenF1 sessions."""
    if not isinstance(sessions, list):
        raise GridUnavailableError("sessions response is not a list")
    finished: list[tuple[dt.datetime, dict[str, Any]]] = []
    for session in sessions:
        if not isinstance(session, dict) or session.get("is_cancelled"):
            continue
        try:
            ended = dt.datetime.fromisoformat(session["date_end"])
            int(session["session_key"])
        except (KeyError, TypeError, ValueError):
            continue
        if ended <= now:
            finished.append((ended, session))
    return max(finished, key=lambda pair: pair[0])[1] if finished else None


class OpenF1Client:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def fetch(self, now: dt.datetime) -> Grid:
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as http:
            # Before a season's first race, the grid is last season's.
            for season in (now.year, now.year - 1):
                race = latest_race(
                    await self._get(http, "/sessions", {"year": season, "session_name": "Race"}),
                    now,
                )
                if race is not None:
                    break
            else:
                raise GridUnavailableError("no finished race in this season or the last")

            drivers = parse_drivers(
                await self._get(http, "/drivers", {"session_key": int(race["session_key"])})
            )
        return Grid(
            season=season,
            race_location=_text(race.get("location")) or _text(race.get("country_name")),
            # date_end was checked by latest_race; a race ends the day it starts.
            race_date=dt.datetime.fromisoformat(race["date_end"]).date(),
            drivers=drivers,
        )

    async def _get(self, http: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await http.get(path, params=params)
        except httpx.HTTPError as error:
            raise GridUnavailableError(f"{type(error).__name__} for {path}") from error
        if response.status_code != 200:
            raise GridUnavailableError(f"HTTP {response.status_code} for {path}")
        try:
            return response.json()
        except ValueError as error:
            raise GridUnavailableError(f"{path} did not return JSON") from error


class GridSource(Protocol):
    """What `GridCache` needs from a client. `OpenF1Client` is the real one."""

    async def fetch(self, now: dt.datetime) -> Grid: ...


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class GridCache:
    """Holds the grid in memory for `ttl`; one refresh at a time."""

    def __init__(
        self,
        source: GridSource,
        *,
        ttl: dt.timedelta,
        now: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._source = source
        self._ttl = ttl
        self._now = now
        self._lock = asyncio.Lock()
        self._cached: tuple[Grid, dt.datetime] | None = None

    async def get(self) -> GridResult:
        async with self._lock:
            now = self._now()
            if self._cached is not None and now - self._cached[1] < self._ttl:
                return GridResult(self._cached[0], self._cached[1], is_stale=False)
            try:
                grid = await self._source.fetch(now)
            except GridUnavailableError:
                if self._cached is None:
                    raise
                logger.warning("OpenF1 refresh failed; serving the grid from %s", self._cached[1])
                return GridResult(self._cached[0], self._cached[1], is_stale=True)
            self._cached = (grid, now)
            return GridResult(grid, now, is_stale=False)
