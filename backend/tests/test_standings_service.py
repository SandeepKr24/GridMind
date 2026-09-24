"""When the standings cache calls jolpica-f1, and what it serves when it can't."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.ingestion.standings_provider import RawStandings, StandingsUnavailableError
from app.ingestion.standings_service import SeasonOutOfRangeError, StandingsService
from app.ingestion.standings_store import (
    ConstructorStandingRow,
    DriverStandingRow,
    FetchRecord,
)

pytestmark = pytest.mark.asyncio

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
TTL = dt.timedelta(hours=24)

ROW = DriverStandingRow(
    position=1,
    driver_ref="antonelli",
    driver_name="Andrea Kimi Antonelli",
    driver_code="ANT",
    constructor_name="Mercedes",
    points=292.0,
    wins=8,
)
TEAM_ROW = ConstructorStandingRow(
    position=1, constructor_ref="mercedes", constructor_name="Mercedes", points=500.0, wins=10
)


class StoreDouble:
    def __init__(self) -> None:
        self.fetches: dict[int, FetchRecord] = {}
        self.saved: list[RawStandings] = []

    async def latest_fetch(self, season: int) -> FetchRecord | None:
        return self.fetches.get(season)

    async def save(self, raw: RawStandings) -> None:
        self.saved.append(raw)
        self.fetches[raw.season] = FetchRecord(raw.round_number, NOW)

    async def read_drivers(self, season: int) -> list[DriverStandingRow]:
        return [ROW] if season in self.fetches else []

    async def read_constructors(self, season: int) -> list[ConstructorStandingRow]:
        return [TEAM_ROW] if season in self.fetches else []


class ClientDouble:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[int] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def fetch(self, season: int) -> RawStandings:
        self.calls.append(season)
        await self.gate.wait()
        if self.error is not None:
            raise self.error
        return RawStandings(season, 14, (), ())


def service(store: StoreDouble, client: ClientDouble) -> StandingsService:
    return StandingsService(store, client, ttl=TTL, now=lambda: NOW)


class TestFreshness:
    async def test_a_season_never_fetched_is_fetched_once(self) -> None:
        store, client = StoreDouble(), ClientDouble()

        result = await service(store, client).drivers(2026)

        assert client.calls == [2026]
        assert result.rows == [ROW]
        assert (result.season, result.round_number, result.is_stale) == (2026, 14, False)

    async def test_fresh_standings_are_served_without_a_call(self) -> None:
        store, client = StoreDouble(), ClientDouble()
        store.fetches[2026] = FetchRecord(14, NOW - dt.timedelta(hours=2))

        await service(store, client).drivers(2026)

        assert client.calls == []

    async def test_stale_standings_trigger_exactly_one_call(self) -> None:
        store, client = StoreDouble(), ClientDouble()
        store.fetches[2026] = FetchRecord(13, NOW - dt.timedelta(hours=25))

        result = await service(store, client).drivers(2026)

        assert client.calls == [2026]
        assert result.round_number == 14

    async def test_a_finished_season_is_never_fetched_again(self) -> None:
        # Fetched after the season ended: those standings are final.
        store, client = StoreDouble(), ClientDouble()
        store.fetches[2024] = FetchRecord(24, dt.datetime(2025, 1, 5, tzinfo=dt.UTC))

        await service(store, client).drivers(2024)

        assert client.calls == []

    async def test_a_past_season_fetched_mid_season_is_refreshed(self) -> None:
        # Fetched in the summer of that year, so the final rounds are missing.
        store, client = StoreDouble(), ClientDouble()
        store.fetches[2025] = FetchRecord(12, dt.datetime(2025, 7, 1, tzinfo=dt.UTC))

        await service(store, client).drivers(2025)

        assert client.calls == [2025]

    async def test_concurrent_requests_share_one_call(self) -> None:
        store, client = StoreDouble(), ClientDouble()
        client.gate.clear()
        standings = service(store, client)

        pending = asyncio.gather(*(standings.drivers(2026) for _ in range(4)))
        await asyncio.sleep(0.01)
        client.gate.set()
        await pending

        assert client.calls == [2026]

    async def test_constructors_share_the_same_refresh(self) -> None:
        store, client = StoreDouble(), ClientDouble()
        standings = service(store, client)

        await standings.drivers(2026)
        result = await standings.constructors(2026)

        assert client.calls == [2026]
        assert result.rows == [TEAM_ROW]


class TestFailures:
    async def test_jolpica_down_serves_stale_rows_marked_stale(self) -> None:
        store = StoreDouble()
        store.fetches[2026] = FetchRecord(13, NOW - dt.timedelta(days=3))
        client = ClientDouble(error=StandingsUnavailableError("HTTP 503"))

        result = await service(store, client).drivers(2026)

        assert result.is_stale
        assert result.round_number == 13
        assert result.rows == [ROW]

    async def test_jolpica_down_with_nothing_stored_is_an_error(self) -> None:
        client = ClientDouble(error=StandingsUnavailableError("HTTP 503"))
        with pytest.raises(StandingsUnavailableError):
            await service(StoreDouble(), client).drivers(2026)

    async def test_a_failure_is_retried_on_the_next_request(self) -> None:
        store = StoreDouble()
        client = ClientDouble(error=StandingsUnavailableError("down"))
        standings = service(store, client)
        with pytest.raises(StandingsUnavailableError):
            await standings.drivers(2026)

        client.error = None
        await standings.drivers(2026)

        assert client.calls == [2026, 2026]

    @pytest.mark.parametrize("season", [1949, 2027, 9999])
    async def test_seasons_outside_the_record_never_reach_upstream(self, season: int) -> None:
        client = ClientDouble()
        with pytest.raises(SeasonOutOfRangeError):
            await service(StoreDouble(), client).drivers(season)
        assert client.calls == []

    async def test_a_season_with_no_races_yet_is_empty_not_an_error(self) -> None:
        store = StoreDouble()
        store.fetches[2026] = FetchRecord(0, NOW)

        result = await service(store, ClientDouble()).drivers(2026)

        assert result.round_number is None
