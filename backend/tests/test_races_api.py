"""Race endpoints.

Two halves. The formatting and id-parsing tests are pure. The endpoint tests
run against the real database, seeding a session inside a rolled-back
transaction, because the shapes they return are assembled by SQL.
"""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.analytics import race_stats
from app.api.routes.races import parse_race_id
from app.api.schemas.race import format_gap, format_lap_time, race_id
from app.ingestion.normalizer import SessionWriter
from tests.conftest_db import (  # noqa: F401
    TEST_SEASON,
    connection,
    database,
    sample_session,
)


class TestLapTimeFormatting:
    """The wire carries formatted strings; the frontend renders them as-is."""

    def test_a_lap_time_reads_like_a_timing_screen(self) -> None:
        assert format_lap_time(104701) == "1:44.701"

    def test_under_a_minute_drops_the_minutes(self) -> None:
        # Sector times and pit stops are shown this way.
        assert format_lap_time(23198) == "23.198"

    def test_milliseconds_are_always_three_digits(self) -> None:
        # "1:23.6" would read as 600ms rather than 60ms.
        assert format_lap_time(83060) == "1:23.060"

    def test_seconds_are_padded_inside_a_minute(self) -> None:
        assert format_lap_time(63000) == "1:03.000"

    def test_exactly_one_minute(self) -> None:
        assert format_lap_time(60000) == "1:00.000"

    @pytest.mark.parametrize("value", [None, -1])
    def test_missing_or_impossible_times_stay_none(self, value: int | None) -> None:
        assert format_lap_time(value) is None

    def test_a_gap_is_signed(self) -> None:
        assert format_gap(1234) == "+1.234"


class TestRaceIdParsing:
    def test_the_frontend_format_round_trips(self) -> None:
        assert parse_race_id(race_id(2024, 14)) == (2024, 14)

    def test_a_single_digit_round(self) -> None:
        assert parse_race_id("2024-1") == (2024, 1)

    @pytest.mark.parametrize(
        "raw",
        [
            "not-a-race",
            "2024",
            "2024-",
            "-14",
            "2024-14-1",
            "20x4-14",
            "2024-0",
            "1990-1",  # before FastF1's timing coverage
            "../admin",
            "2024-14; drop table laps",
        ],
    )
    def test_anything_else_is_a_404_not_a_crash(self, raw: str) -> None:
        # These arrive from a URL anyone can edit, so they must never reach
        # the query layer.
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            parse_race_id(raw)
        assert error.value.status_code == 404


pytestmark_db = pytest.mark.asyncio


@pytest.mark.asyncio
class TestCalendar:
    async def test_lists_a_stored_round(self, connection: AsyncConnection) -> None:  # noqa: F811
        await SessionWriter(connection).store(sample_session())
        rounds = await race_stats.get_calendar(connection, TEST_SEASON)

        assert len(rounds) == 1
        assert rounds[0].event_name == "Test Grand Prix"
        assert rounds[0].state == "ingested"
        # The race distance, taken from the winner's lap count.
        assert rounds[0].total_laps == 2

    async def test_an_unknown_season_is_empty_not_an_error(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # The database starts empty and fills as people ask. An empty calendar
        # is a truthful answer, and the UI shows an empty state.
        assert await race_stats.get_calendar(connection, 1999) == []

    async def test_a_session_that_is_not_complete_reads_as_available(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Stored but not marked ingested, and the race has already run:
        # asking about it triggers a fetch.
        import dataclasses
        import datetime as dt

        from tests.conftest_db import EVENT

        # A date genuinely in the past. The fixture season is 2099 precisely so
        # its rows cannot collide with real data, which also makes its own
        # event date "upcoming" — hence the explicit override here.
        past = dataclasses.replace(EVENT, event_date=dt.date(2020, 1, 1))
        await SessionWriter(connection).store(
            sample_session(event=past, laps=(), pit_stops=(), is_partial=True)
        )
        rounds = await race_stats.get_calendar(connection, TEST_SEASON)
        assert rounds[0].state == "available"

    async def test_a_race_that_has_not_run_reads_as_upcoming(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # The fixture season is far in the future, so this is the natural case.
        await SessionWriter(connection).store(
            sample_session(laps=(), pit_stops=(), is_partial=True)
        )
        rounds = await race_stats.get_calendar(connection, TEST_SEASON)
        assert rounds[0].state == "upcoming"


@pytest.mark.asyncio
class TestRaceDetail:
    async def test_reports_the_winner_and_fastest_lap(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        detail = await race_stats.get_race(connection, TEST_SEASON, 1)

        assert detail is not None
        assert detail.id == f"{TEST_SEASON}-1"
        assert detail.winner_name == "Max Verstappen"
        # 82000ms, and not Norris's quicker deleted lap.
        assert detail.fastest_lap_time == "1:22.000"
        assert detail.fastest_lap_driver == "Max Verstappen"

    async def test_an_unstored_race_is_none(self, connection: AsyncConnection) -> None:  # noqa: F811
        assert await race_stats.get_race(connection, TEST_SEASON, 99) is None

    async def test_winning_margin_is_null_because_we_do_not_store_race_time(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        detail = await race_stats.get_race(connection, TEST_SEASON, 1)
        assert detail is not None
        assert detail.winning_margin is None


@pytest.mark.asyncio
class TestRaceStats:
    async def test_classification_is_ordered_by_position(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)

        assert stats is not None
        assert [row.position for row in stats.classification] == [1, 2]
        assert stats.classification[0].driver_name == "Max Verstappen"
        assert stats.classification[0].constructor_name == "Red Bull Racing"

    async def test_gap_to_leader_is_never_invented(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # "Gap to leader" means the race finishing gap. We store lap times, not
        # race time, so the honest answer is nothing at all. An earlier draft
        # filled it with a best-lap delta — a different number under this
        # one's name.
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)
        assert stats is not None
        assert all(row.gap_to_leader is None for row in stats.classification)

    async def test_position_changes_are_biggest_mover_first(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)
        assert stats is not None
        gained = [c.positions_gained for c in stats.position_changes]
        assert gained == sorted(gained, reverse=True)

    async def test_pace_traces_cover_the_podium_only(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # A 20-driver trace is unreadable and ships a megabyte to a phone.
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)
        assert stats is not None
        assert len(stats.pace_traces) <= 3

    async def test_stints_are_runs_of_one_compound(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # FastF1 gives compound per lap, not per stint, so the boundaries are
        # derived. Two laps on MEDIUM is one stint, and therefore no stops.
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)
        assert stats is not None
        strategy = next(s for s in stats.strategies if s.driver_code == "VER")
        assert len(strategy.stints) == 1
        assert strategy.stints[0].compound == "MEDIUM"
        assert (strategy.stints[0].start_lap, strategy.stints[0].end_lap) == (1, 2)
        assert strategy.stop_count == 0

    async def test_a_fresh_set_of_the_same_compound_is_a_new_stint(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Seen at Spa 2024: HARD -> HARD stops vanished, so Hamilton read as
        # one stop with two stints while the pit stop table listed two.
        base = sample_session()
        verstappen = [lap for lap in base.laps if lap.driver_ref == "max_verstappen"]
        fresh_set = dataclasses.replace(verstappen[-1], lap_number=3, tyre_life=1)
        laps = (*base.laps, fresh_set)
        await SessionWriter(connection).store(sample_session(laps=laps))

        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)

        assert stats is not None
        strategy = next(s for s in stats.strategies if s.driver_code == "VER")
        assert [(s.compound, s.start_lap, s.end_lap) for s in strategy.stints] == [
            ("MEDIUM", 1, 2),
            ("MEDIUM", 3, 3),
        ]
        assert strategy.stop_count == 1

    async def test_pit_stops_are_fastest_first(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        stats = await race_stats.get_race_stats(connection, TEST_SEASON, 1)
        assert stats is not None
        assert stats.pit_stops[0].duration_seconds == 23.0

    async def test_an_unstored_race_has_no_stats(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        assert await race_stats.get_race_stats(connection, TEST_SEASON, 99) is None


@pytest.mark.asyncio
class TestDashboard:
    async def test_counts_what_is_actually_stored(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        data = await race_stats.get_dashboard(connection, TEST_SEASON)

        assert data.rounds_ingested == 1
        assert data.rounds_on_calendar == 1
        assert data.laps_stored == 4
        assert data.latest_race is not None
        assert data.latest_race.winner_name == "Max Verstappen"
        assert len(data.latest_podium) == 2

    async def test_an_empty_season_reports_zeroes_not_nulls(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        data = await race_stats.get_dashboard(connection, 1999)
        assert (data.rounds_ingested, data.rounds_on_calendar, data.laps_stored) == (0, 0, 0)
        assert data.latest_race is None
