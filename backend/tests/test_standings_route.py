"""`GET /api/standings/{year}/drivers|constructors`, over a real StandingsService."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingestion.standings_provider import StandingsUnavailableError
from app.ingestion.standings_service import StandingsService
from app.main import create_app
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble
from tests.test_standings_service import NOW, TTL, ClientDouble, StoreDouble


class Harness:
    def __init__(self) -> None:
        self.store, self.client_double = StoreDouble(), ClientDouble()
        standings = StandingsService(self.store, self.client_double, ttl=TTL, now=lambda: NOW)
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, database_url=WRITER, database_url_readonly=READER
        )
        app = create_app(
            settings=settings,
            database=DatabaseDouble(),  # type: ignore[arg-type]
            schedules=SchedulesDouble(()),
            standings=standings,
        )
        self.http = TestClient(app)


@pytest.fixture
def harness() -> Iterator[Harness]:
    h = Harness()
    with h.http:
        yield h


class TestDriverStandings:
    def test_serves_the_table_with_its_freshness(self, harness: Harness) -> None:
        body = harness.http.get("/api/standings/2026/drivers").json()

        assert (body["season"], body["round"], body["is_stale"]) == (2026, 14, False)
        assert body["fetched_at"] == NOW.isoformat()
        assert body["standings"] == [
            {
                "position": 1,
                "driver_ref": "antonelli",
                "driver_name": "Andrea Kimi Antonelli",
                "driver_code": "ANT",
                "constructor_name": "Mercedes",
                "points": 292.0,
                "wins": 8,
            }
        ]

    def test_a_season_with_no_championship_is_404(self, harness: Harness) -> None:
        assert harness.http.get("/api/standings/1949/drivers").status_code == 404
        assert harness.client_double.calls == []

    def test_upstream_down_with_nothing_stored_is_503(self, harness: Harness) -> None:
        harness.client_double.error = StandingsUnavailableError("HTTP 503 from jolpi.ca")

        response = harness.http.get("/api/standings/2026/drivers")

        assert response.status_code == 503
        assert "jolpi" not in response.text
        assert response.headers["retry-after"] == "300"


class TestConstructorStandings:
    def test_serves_the_table(self, harness: Harness) -> None:
        body = harness.http.get("/api/standings/2026/constructors").json()

        assert body["round"] == 14
        assert body["standings"] == [
            {
                "position": 1,
                "constructor_ref": "mercedes",
                "constructor_name": "Mercedes",
                "points": 500.0,
                "wins": 10,
            }
        ]

    def test_a_non_numeric_year_is_422(self, harness: Harness) -> None:
        assert harness.http.get("/api/standings/latest/constructors").status_code == 422
