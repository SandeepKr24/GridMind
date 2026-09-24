"""The jolpica-f1 client: parsing, retries and failures. No network."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.ingestion.standings_provider import (
    JolpicaClient,
    StandingsUnavailableError,
    parse_constructor_standings,
    parse_driver_standings,
)

BASE = "https://api.jolpi.ca/ergast/f1"


def driver_payload(round_number: str = "24", rows: list[dict[str, Any]] | None = None) -> dict:
    standings = (
        rows
        if rows is not None
        else [
            {
                "position": "1",
                "positionText": "1",
                "points": "437",
                "wins": "9",
                "Driver": {
                    "driverId": "max_verstappen",
                    "permanentNumber": "3",
                    "code": "VER",
                    "givenName": "Max",
                    "familyName": "Verstappen",
                    "nationality": "Dutch",
                },
                "Constructors": [{"constructorId": "red_bull", "name": "Red Bull"}],
            },
            {
                "position": "2",
                "positionText": "2",
                "points": "374.5",
                "wins": "4",
                "Driver": {"driverId": "norris", "givenName": "Lando", "familyName": "Norris"},
                "Constructors": [{"constructorId": "mclaren", "name": "McLaren"}],
            },
        ]
    )
    lists = [{"season": "2024", "round": round_number, "DriverStandings": standings}]
    return {"MRData": {"StandingsTable": {"season": "2024", "StandingsLists": lists}}}


def constructor_payload() -> dict:
    lists = [
        {
            "season": "2024",
            "round": "24",
            "ConstructorStandings": [
                {
                    "position": "1",
                    "points": "666",
                    "wins": "6",
                    "Constructor": {
                        "constructorId": "mclaren",
                        "name": "McLaren",
                        "nationality": "British",
                    },
                }
            ],
        }
    ]
    return {"MRData": {"StandingsTable": {"season": "2024", "StandingsLists": lists}}}


EMPTY = {"MRData": {"StandingsTable": {"season": "2027", "StandingsLists": []}}}


class TestParsing:
    def test_reads_a_driver_row(self) -> None:
        round_number, rows = parse_driver_standings(driver_payload())

        assert round_number == 24
        first = rows[0]
        assert (first.driver_ref, first.code, first.full_name) == (
            "max_verstappen",
            "VER",
            "Max Verstappen",
        )
        assert (first.position, first.points, first.wins) == (1, 437.0, 9)
        assert (first.constructor_ref, first.constructor_name) == ("red_bull", "Red Bull")
        assert first.permanent_number == 3

    def test_half_points_survive(self) -> None:
        # Shortened races award half points.
        assert parse_driver_standings(driver_payload())[1][1].points == 374.5

    def test_missing_optional_fields_are_none(self) -> None:
        second = parse_driver_standings(driver_payload())[1][1]
        assert (second.code, second.permanent_number, second.nationality) == (None, None, None)

    def test_a_disqualified_driver_has_no_position(self) -> None:
        # Schumacher 1997: in the list, but "-" rather than a place.
        row = dict(
            driver_payload()["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"][0]
        )
        row = {k: v for k, v in row.items() if k != "position"} | {"positionText": "-"}
        _, rows = parse_driver_standings(driver_payload(rows=[row]))
        assert rows[0].position is None

    def test_a_mid_season_move_uses_the_latest_team(self) -> None:
        row = dict(
            driver_payload()["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"][0]
        )
        row["Constructors"] = [
            {"constructorId": "red_bull", "name": "Red Bull"},
            {"constructorId": "rb", "name": "RB F1 Team"},
        ]
        _, rows = parse_driver_standings(driver_payload(rows=[row]))
        assert rows[0].constructor_ref == "rb"

    def test_a_season_that_has_not_started_is_empty(self) -> None:
        assert parse_driver_standings(EMPTY) == (0, ())

    def test_reads_a_constructor_row(self) -> None:
        round_number, rows = parse_constructor_standings(constructor_payload())
        assert round_number == 24
        assert (rows[0].constructor_ref, rows[0].name, rows[0].points, rows[0].position) == (
            "mclaren",
            "McLaren",
            666.0,
            1,
        )

    @pytest.mark.parametrize(
        "payload",
        [{}, {"MRData": {}}, {"MRData": {"StandingsTable": {"StandingsLists": "nope"}}}],
    )
    def test_a_malformed_payload_is_unavailable_not_a_crash(self, payload: dict) -> None:
        with pytest.raises(StandingsUnavailableError):
            parse_driver_standings(payload)

    def test_a_row_without_points_is_unavailable(self) -> None:
        row = {"position": "1", "Driver": {"driverId": "x", "familyName": "X"}}
        with pytest.raises(StandingsUnavailableError):
            parse_driver_standings(driver_payload(rows=[row]))


def client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[JolpicaClient, list[str]]:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    async def no_sleep(_: float) -> None:
        return None

    jolpica = JolpicaClient(BASE, transport=httpx.MockTransport(record), sleep=no_sleep, retries=2)
    return jolpica, seen


def ok(request: httpx.Request) -> httpx.Response:
    if "constructorStandings" in request.url.path:
        return httpx.Response(200, json=constructor_payload())
    return httpx.Response(200, json=driver_payload())


@pytest.mark.asyncio
class TestClient:
    async def test_fetches_both_tables_for_a_season(self) -> None:
        jolpica, seen = client(ok)

        standings = await jolpica.fetch(2024)

        assert standings.season == 2024
        assert standings.round_number == 24
        assert len(standings.drivers) == 2
        assert len(standings.constructors) == 1
        assert seen == [
            f"{BASE}/2024/driverStandings.json?limit=100",
            f"{BASE}/2024/constructorStandings.json?limit=100",
        ]

    async def test_a_transient_failure_is_retried(self) -> None:
        attempts = 0

        def flaky(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
            return ok(request)

        jolpica, seen = client(flaky)
        standings = await jolpica.fetch(2024)

        assert len(standings.drivers) == 2
        assert len(seen) == 3

    async def test_rate_limiting_is_retried(self) -> None:
        attempts = 0

        def limited(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429) if attempts == 1 else ok(request)

        jolpica, _ = client(limited)
        assert (await jolpica.fetch(2024)).round_number == 24

    async def test_retries_are_bounded(self) -> None:
        jolpica, seen = client(lambda _: httpx.Response(503))

        with pytest.raises(StandingsUnavailableError):
            await jolpica.fetch(2024)
        # One try plus two retries, then give up: never a loop.
        assert len(seen) == 3

    async def test_a_client_error_is_not_retried(self) -> None:
        jolpica, seen = client(lambda _: httpx.Response(404))

        with pytest.raises(StandingsUnavailableError):
            await jolpica.fetch(2024)
        assert len(seen) == 1

    async def test_a_network_error_is_unavailable(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        jolpica, _ = client(down)
        with pytest.raises(StandingsUnavailableError):
            await jolpica.fetch(2024)

    async def test_a_body_that_is_not_json_is_unavailable(self) -> None:
        jolpica, _ = client(lambda _: httpx.Response(200, text="<html>maintenance</html>"))
        with pytest.raises(StandingsUnavailableError):
            await jolpica.fetch(2024)

    async def test_tables_at_different_rounds_are_not_stored_mislabelled(self) -> None:
        # Just after a race one table can update before the other. Saving both
        # under one round would label the lagging table wrongly.
        def split(request: httpx.Request) -> httpx.Response:
            if "constructorStandings" in request.url.path:
                return httpx.Response(200, json=constructor_payload())
            return httpx.Response(200, json=driver_payload(round_number="25"))

        jolpica, _ = client(split)
        with pytest.raises(StandingsUnavailableError, match="rounds"):
            await jolpica.fetch(2024)

    async def test_a_season_before_the_constructors_title_is_drivers_only(self) -> None:
        # No constructors' championship until 1958: an empty table is not a
        # mismatch.
        def early(request: httpx.Request) -> httpx.Response:
            if "constructorStandings" in request.url.path:
                return httpx.Response(200, json=EMPTY)
            return httpx.Response(200, json=driver_payload(round_number="7"))

        jolpica, _ = client(early)
        standings = await jolpica.fetch(1955)

        assert standings.round_number == 7
        assert standings.constructors == ()
