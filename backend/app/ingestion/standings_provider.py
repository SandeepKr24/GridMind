"""Championship standings from jolpica-f1.

Season standings cannot be derived from what we store: on-demand ingestion
holds only the sessions somebody asked about. They come from jolpica-f1, the
free community successor to Ergast, which is rate-limited — so this client makes
exactly two requests per refresh (drivers, constructors), retries a transient
failure a bounded number of times, and is only ever called through the cache in
`standings_service.py`.

jolpica's driver and constructor ids are the Ergast references FastF1 also uses
(`max_verstappen`, `red_bull`), so standings rows join onto the same drivers
and constructors that ingestion writes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: A season lists every driver who scored or started; 100 covers any year.
PAGE_LIMIT = 100
TIMEOUT_SECONDS = 10.0
#: Status codes worth another attempt. Anything else in 4xx will not improve.
RETRYABLE = frozenset({429, 500, 502, 503, 504})


class StandingsUnavailableError(RuntimeError):
    """jolpica-f1 could not supply usable standings."""


@dataclass(frozen=True, slots=True)
class RawDriverStanding:
    driver_ref: str
    code: str | None
    first_name: str | None
    last_name: str | None
    full_name: str
    nationality: str | None
    permanent_number: int | None
    #: The team at the latest round; a mid-season move lists several.
    constructor_ref: str | None
    constructor_name: str | None
    #: None for a driver excluded from the championship (positionText "-").
    position: int | None
    points: float
    wins: int | None


@dataclass(frozen=True, slots=True)
class RawConstructorStanding:
    constructor_ref: str
    name: str
    nationality: str | None
    position: int | None
    points: float
    wins: int | None


@dataclass(frozen=True, slots=True)
class RawStandings:
    season: int
    #: The round the standings are after; 0 if the season has not started.
    round_number: int
    drivers: tuple[RawDriverStanding, ...]
    constructors: tuple[RawConstructorStanding, ...]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _standings_list(payload: Any, key: str) -> tuple[int, list[dict[str, Any]]]:
    try:
        lists = payload["MRData"]["StandingsTable"]["StandingsLists"]
        if not isinstance(lists, list):
            raise TypeError("StandingsLists is not a list")
        if not lists:
            return 0, []
        latest = lists[-1]
        return int(latest["round"]), list(latest[key])
    except (KeyError, TypeError, ValueError) as error:
        raise StandingsUnavailableError(f"unexpected standings payload: {error}") from error


def parse_driver_standings(payload: Any) -> tuple[int, tuple[RawDriverStanding, ...]]:
    round_number, rows = _standings_list(payload, "DriverStandings")
    try:
        return round_number, tuple(_driver_row(row) for row in rows)
    except (KeyError, TypeError, ValueError) as error:
        raise StandingsUnavailableError(f"unreadable driver standing: {error}") from error


def _driver_row(row: dict[str, Any]) -> RawDriverStanding:
    driver = row["Driver"]
    teams = row.get("Constructors") or []
    team = teams[-1] if teams else {}
    first, last = driver.get("givenName"), driver.get("familyName")
    return RawDriverStanding(
        driver_ref=driver["driverId"],
        code=driver.get("code"),
        first_name=first,
        last_name=last,
        full_name=" ".join(part for part in (first, last) if part) or driver["driverId"],
        nationality=driver.get("nationality"),
        permanent_number=_int(driver.get("permanentNumber")),
        constructor_ref=team.get("constructorId"),
        constructor_name=team.get("name"),
        position=_int(row.get("position")),
        points=float(row["points"]),
        wins=_int(row.get("wins")),
    )


def parse_constructor_standings(
    payload: Any,
) -> tuple[int, tuple[RawConstructorStanding, ...]]:
    round_number, rows = _standings_list(payload, "ConstructorStandings")
    try:
        return round_number, tuple(
            RawConstructorStanding(
                constructor_ref=row["Constructor"]["constructorId"],
                name=row["Constructor"].get("name") or row["Constructor"]["constructorId"],
                nationality=row["Constructor"].get("nationality"),
                position=_int(row.get("position")),
                points=float(row["points"]),
                wins=_int(row.get("wins")),
            )
            for row in rows
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StandingsUnavailableError(f"unreadable constructor standing: {error}") from error


class JolpicaClient:
    def __init__(
        self,
        base_url: str,
        *,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._retries = retries
        self._transport = transport
        self._sleep = sleep

    async def fetch(self, season: int) -> RawStandings:
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=TIMEOUT_SECONDS, transport=self._transport
        ) as http:
            drivers_payload = await self._get(http, f"/{season}/driverStandings.json")
            constructors_payload = await self._get(http, f"/{season}/constructorStandings.json")

        round_number, drivers = parse_driver_standings(drivers_payload)
        constructor_round, constructors = parse_constructor_standings(constructors_payload)
        # Right after a race one table can update before the other. Refuse
        # rather than store the lagging one under the wrong round; the cache
        # serves the previous standings and the next request tries again.
        # An empty constructors table (no title before 1958) is not a mismatch.
        if constructors and constructor_round != round_number:
            raise StandingsUnavailableError(
                f"driver and constructor standings are at different rounds "
                f"({round_number} vs {constructor_round})"
            )
        return RawStandings(season, round_number, drivers, constructors)

    async def _get(self, http: httpx.AsyncClient, path: str) -> Any:
        for attempt in range(self._retries + 1):
            try:
                response = await http.get(path, params={"limit": PAGE_LIMIT})
            except httpx.HTTPError as error:
                failure = f"{type(error).__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as error:
                        raise StandingsUnavailableError("response was not JSON") from error
                if response.status_code not in RETRYABLE:
                    raise StandingsUnavailableError(f"HTTP {response.status_code} for {path}")
                failure = f"HTTP {response.status_code}"

            if attempt < self._retries:
                logger.warning("jolpica %s: %s; retrying", path, failure)
                await self._sleep(2.0**attempt)
        raise StandingsUnavailableError(f"{failure} for {path} after {self._retries + 1} tries")
