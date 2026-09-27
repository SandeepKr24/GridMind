"""The current grid: OpenF1 parsing, the client, the cache and `GET /api/grid`."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingestion.grid import (
    Grid,
    GridCache,
    GridDriver,
    GridUnavailableError,
    OpenF1Client,
    latest_race,
    parse_drivers,
)
from app.main import create_app
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble

BASE = "https://openf1.test/v1"
RACES_2026 = "sessions?year=2026&session_name=Race"
RACES_2025 = "sessions?year=2025&session_name=Race"
NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)
SMALL = (
    "https://media.formula1.com/d_driver_fallback_image.png/content/dam/fom-website/"
    "drivers/L/LANNOR01_Lando_Norris/lannor01.png.transform/1col/image.png"
)


def driver_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "driver_number": 1,
        "name_acronym": "NOR",
        "first_name": "Lando",
        "last_name": "Norris",
        "team_name": "McLaren",
        "team_colour": "F47600",
        "headshot_url": SMALL,
    }
    row.update(overrides)
    return row


def session(key: int, end: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "session_key": key,
        "date_start": end.replace("13:00", "11:00"),
        "date_end": end,
        "location": "Baku",
        "is_cancelled": False,
    }
    row.update(overrides)
    return row


class TestParseDrivers:
    def test_reads_a_driver_and_asks_for_the_larger_headshot(self) -> None:
        (driver,) = parse_drivers([driver_row()])

        assert driver == GridDriver(
            number=1,
            code="NOR",
            first_name="Lando",
            last_name="Norris",
            team_name="McLaren",
            team_colour="#F47600",
            headshot_url=SMALL.replace("/1col/", "/2col/"),
        )

    @pytest.mark.parametrize(
        "url",
        ["https://evil.example/x.png", "javascript:alert(1)", None, 42],
    )
    def test_keeps_headshots_only_on_f1_media(self, url: object) -> None:
        (driver,) = parse_drivers([driver_row(headshot_url=url)])
        assert driver.headshot_url is None

    @pytest.mark.parametrize("colour", ["red", "#F47600", "F4760", None])
    def test_drops_a_colour_that_is_not_six_hex_digits(self, colour: object) -> None:
        (driver,) = parse_drivers([driver_row(team_colour=colour)])
        assert driver.team_colour is None

    def test_drops_rows_without_a_number_code_surname_or_team(self) -> None:
        drivers = parse_drivers(
            [
                driver_row(),
                driver_row(driver_number="5"),
                driver_row(driver_number=6, name_acronym=""),
                driver_row(driver_number=7, last_name=None),
                driver_row(driver_number=8, team_name=" "),
                "not a row",
            ]
        )
        assert [d.number for d in drivers] == [1]

    def test_sorts_by_number_and_keeps_one_row_per_number(self) -> None:
        drivers = parse_drivers(
            [driver_row(driver_number=81, name_acronym="PIA"), driver_row(), driver_row()]
        )
        assert [d.code for d in drivers] == ["NOR", "PIA"]

    @pytest.mark.parametrize("payload", [[], {"detail": "limited"}, [driver_row(team_name="")]])
    def test_nothing_usable_is_an_error(self, payload: object) -> None:
        with pytest.raises(GridUnavailableError):
            parse_drivers(payload)


class TestLatestRace:
    def test_picks_the_most_recent_finished_race(self) -> None:
        races = [
            session(1, "2026-09-13T15:00:00+00:00"),
            session(2, "2026-09-26T13:00:00+00:00"),
            session(3, "2026-10-04T13:00:00+00:00"),  # not run yet
        ]
        assert latest_race(races, NOW)["session_key"] == 2  # type: ignore[index]

    def test_skips_cancelled_and_malformed_races(self) -> None:
        races = [
            session(1, "2026-09-13T15:00:00+00:00"),
            session(2, "2026-09-26T13:00:00+00:00", is_cancelled=True),
            session(4, "not a date"),
            {"session_key": 5},
        ]
        assert latest_race(races, NOW)["session_key"] == 1  # type: ignore[index]

    def test_none_before_the_first_race(self) -> None:
        assert latest_race([session(1, "2026-10-04T13:00:00+00:00")], NOW) is None


def openf1(routes: dict[str, Any]) -> tuple[OpenF1Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = f"{request.url.path.rsplit('/', 1)[-1]}?{request.url.query.decode()}"
        if key not in routes:
            return httpx.Response(404)
        body = routes[key]
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    return OpenF1Client(BASE, transport=httpx.MockTransport(handle)), seen


class TestOpenF1Client:
    async def test_reads_the_drivers_of_the_latest_race(self) -> None:
        client, seen = openf1(
            {
                RACES_2026: [session(11377, "2026-09-26T13:00:00+00:00")],
                "drivers?session_key=11377": [driver_row()],
            }
        )

        grid = await client.fetch(NOW)

        assert (grid.season, grid.race_location, grid.race_date) == (
            2026,
            "Baku",
            dt.date(2026, 9, 26),
        )
        assert [d.code for d in grid.drivers] == ["NOR"]
        assert len(seen) == 2

    async def test_before_the_season_starts_it_uses_last_season(self) -> None:
        client, _ = openf1(
            {
                RACES_2026: [],
                RACES_2025: [session(9999, "2025-12-07T15:00:00+00:00")],
                "drivers?session_key=9999": [driver_row()],
            }
        )
        assert (await client.fetch(NOW)).season == 2025

    @pytest.mark.parametrize(
        "failure",
        [httpx.Response(429), httpx.Response(200, content=b"<html>")],
    )
    async def test_an_upstream_failure_is_grid_unavailable(self, failure: httpx.Response) -> None:
        client, _ = openf1({RACES_2026: failure})
        with pytest.raises(GridUnavailableError):
            await client.fetch(NOW)


GRID = Grid(2026, "Baku", dt.date(2026, 9, 26), parse_drivers([driver_row()]))


class SourceDouble:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def fetch(self, now: dt.datetime) -> Grid:
        self.calls += 1
        if self.fail:
            raise GridUnavailableError("down")
        return GRID


class TestGridCache:
    async def test_serves_from_memory_within_the_ttl(self) -> None:
        clock = [NOW]
        source = SourceDouble()
        cache = GridCache(source, ttl=dt.timedelta(hours=6), now=lambda: clock[0])

        await cache.get()
        clock[0] = NOW + dt.timedelta(hours=5)
        result = await cache.get()

        assert source.calls == 1
        assert (result.fetched_at, result.is_stale) == (NOW, False)

    async def test_refreshes_after_the_ttl(self) -> None:
        clock = [NOW]
        source = SourceDouble()
        cache = GridCache(source, ttl=dt.timedelta(hours=6), now=lambda: clock[0])

        await cache.get()
        clock[0] = NOW + dt.timedelta(hours=7)
        await cache.get()

        assert source.calls == 2

    async def test_a_failed_refresh_serves_the_old_copy_as_stale(self) -> None:
        clock = [NOW]
        source = SourceDouble()
        cache = GridCache(source, ttl=dt.timedelta(hours=6), now=lambda: clock[0])
        await cache.get()

        source.fail = True
        clock[0] = NOW + dt.timedelta(hours=7)
        result = await cache.get()

        assert result.is_stale
        assert result.grid is GRID

    async def test_with_nothing_cached_a_failure_propagates(self) -> None:
        source = SourceDouble()
        source.fail = True
        with pytest.raises(GridUnavailableError):
            await GridCache(source, ttl=dt.timedelta(hours=6), now=lambda: NOW).get()


class Harness:
    def __init__(self) -> None:
        self.source = SourceDouble()
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, database_url=WRITER, database_url_readonly=READER
        )
        app = create_app(
            settings=settings,
            database=DatabaseDouble(),  # type: ignore[arg-type]
            schedules=SchedulesDouble(()),
            grid_source=self.source,
        )
        self.http = TestClient(app)


@pytest.fixture
def harness() -> Iterator[Harness]:
    h = Harness()
    with h.http:
        yield h


class TestGridRoute:
    def test_serves_every_field_the_pages_read(self, harness: Harness) -> None:
        body = harness.http.get("/api/grid").json()

        assert (body["season"], body["race_location"], body["race_date"]) == (
            2026,
            "Baku",
            "2026-09-26",
        )
        assert body["is_stale"] is False
        assert body["drivers"] == [
            {
                "number": 1,
                "code": "NOR",
                "first_name": "Lando",
                "last_name": "Norris",
                "team_name": "McLaren",
                "team_colour": "#F47600",
                "headshot_url": SMALL.replace("/1col/", "/2col/"),
            }
        ]

    def test_unavailable_is_503_with_retry_after(self, harness: Harness) -> None:
        harness.source.fail = True

        response = harness.http.get("/api/grid")

        assert response.status_code == 503
        assert response.headers["retry-after"] == "300"
