"""The calendar and dashboard routes combine storage with the published schedule.

The queries themselves are covered against a real database in
`test_races_api.py`; here they are replaced so the routes can be tested for
what they add — the merge with the schedule — without Postgres.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analytics import race_stats
from app.api.schemas.race import CalendarRound
from app.config import Settings
from app.ingestion.base import RawEvent
from app.main import create_app
from app.reports import store as report_store

WRITER = "postgresql://neondb_owner:pw@ep-x.aws.neon.tech/neondb"
READER = "postgresql://gridmind_readonly:pw2@ep-x.aws.neon.tech/neondb"


class DatabaseDouble:
    @asynccontextmanager
    async def connect(self, *, read_only: bool = False) -> AsyncIterator[None]:
        yield None

    async def dispose(self) -> None:
        return None


class SchedulesDouble:
    def __init__(self, events: tuple[RawEvent, ...]) -> None:
        self.events = events
        self.requested: list[int] = []

    async def get(self, season: int) -> tuple[RawEvent, ...]:
        self.requested.append(season)
        return self.events


def event(round_number: int, event_date: dt.date) -> RawEvent:
    return RawEvent(
        season=2024,
        round_number=round_number,
        event_name=f"Round {round_number} Grand Prix",
        official_name=None,
        event_date=event_date,
        country="Belgium",
        location="Spa-Francorchamps",
        event_format="conventional",
    )


STORED = CalendarRound(
    season=2024,
    round=14,
    event_name="Belgian Grand Prix",
    circuit_name="Spa-Francorchamps",
    country="Belgium",
    event_date="2024-07-28",
    state="ingested",
    total_laps=44,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def get_calendar(connection: Any, season: int) -> list[CalendarRound]:
        return [STORED] if season == 2024 else []

    monkeypatch.setattr(race_stats, "get_calendar", get_calendar)

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=WRITER, database_url_readonly=READER
    )
    schedules = SchedulesDouble((event(1, dt.date(2024, 3, 2)), event(14, dt.date(2024, 7, 28))))
    app = create_app(
        settings=settings,
        database=DatabaseDouble(),  # type: ignore[arg-type]
        schedules=schedules,
    )
    return TestClient(app)


class TestCalendarRoute:
    def test_lists_scheduled_rounds_nobody_has_asked_about(self, client: TestClient) -> None:
        with client:
            body = client.get("/api/seasons/2024/calendar").json()

        assert [(r["round"], r["state"]) for r in body] == [(1, "available"), (14, "ingested")]

    def test_a_stored_round_keeps_its_lap_count(self, client: TestClient) -> None:
        with client:
            body = client.get("/api/seasons/2024/calendar").json()
        assert body[1]["total_laps"] == 44


class TestDashboardRoute:
    def test_counts_the_whole_calendar_not_just_stored_rounds(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def get_dashboard(connection: Any, season: int) -> race_stats.DashboardData:
            return race_stats.DashboardData(
                season=season,
                rounds_ingested=1,
                rounds_on_calendar=1,
                laps_stored=917,
                latest_race=None,
                latest_podium=[],
            )

        async def count_reports(connection: Any, season: int) -> int:
            return 3

        async def latest_report(connection: Any, season: int) -> None:
            return None

        monkeypatch.setattr(race_stats, "get_dashboard", get_dashboard)
        monkeypatch.setattr(report_store, "count_reports", count_reports)
        monkeypatch.setattr(report_store, "latest_report", latest_report)
        with client:
            body = client.get("/api/dashboard", params={"season": 2024}).json()

        assert (body["rounds_ingested"], body["rounds_on_calendar"]) == (1, 2)
        assert (body["reports_written"], body["latest_report"]) == (3, None)


class TestRaceDetailRoute:
    @pytest.fixture
    def nothing_stored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def get_race(connection: Any, season: int, round_number: int) -> None:
            return None

        monkeypatch.setattr(race_stats, "get_race", get_race)

    @pytest.mark.usefixtures("nothing_stored")
    def test_a_scheduled_race_not_yet_fetched_is_available(self, client: TestClient) -> None:
        # The detail page offers the fetch from here, so it needs the header,
        # not a 404.
        with client:
            response = client.get("/api/races/2024-1")

        assert response.status_code == 200
        body = response.json()
        assert (body["id"], body["event_name"], body["state"]) == (
            "2024-1",
            "Round 1 Grand Prix",
            "available",
        )
        assert body["winner_name"] is None
        assert body["total_laps"] is None

    @pytest.mark.usefixtures("nothing_stored")
    def test_a_round_on_no_calendar_is_still_a_404(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/races/2024-9")
        assert response.status_code == 404
