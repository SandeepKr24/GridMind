"""Storing a fetched session.

These run against the real database inside a transaction that is rolled back.
That is deliberate: the behaviour under test *is* Postgres behaviour — `ON
CONFLICT` resolution, unique constraints, foreign keys — and a mock would
assert only that we called the functions we wrote.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import (
    Constructor,
    Driver,
    DriverSeason,
    Lap,
    Meeting,
    PitStop,
    RaceControlEvent,
    Season,
    Session,
    SessionResult,
)
from app.ingestion.normalizer import SessionWriter
from tests.conftest_db import (  # noqa: F401
    TEST_SEASON,
    connection,
    database,
    sample_session,
)

pytestmark = pytest.mark.asyncio


async def count(conn: AsyncConnection, table: object, **where: object) -> int:
    statement = select(func.count()).select_from(table)  # type: ignore[arg-type]
    for column, value in where.items():
        statement = statement.where(getattr(table, column) == value)
    return int((await conn.execute(statement)).scalar_one())


class TestFirstIngest:
    async def test_writes_the_whole_session(self, connection: AsyncConnection) -> None:  # noqa: F811
        stored = await SessionWriter(connection).store(sample_session())

        assert stored.rows_written == 2 + 4 + 1 + 2  # results, laps, pits, messages
        assert stored.is_complete is True
        assert await count(connection, Lap, session_id=stored.session_id) == 4
        assert await count(connection, SessionResult, session_id=stored.session_id) == 2
        assert await count(connection, PitStop, session_id=stored.session_id) == 1
        assert await count(connection, RaceControlEvent, session_id=stored.session_id) == 2

    async def test_creates_the_calendar_spine(self, connection: AsyncConnection) -> None:  # noqa: F811
        stored = await SessionWriter(connection).store(sample_session())

        season = (await connection.execute(select(Season).where(Season.year == TEST_SEASON))).one()
        assert season.year == TEST_SEASON

        meeting = (
            await connection.execute(select(Meeting).where(Meeting.id == stored.meeting_id))
        ).one()
        assert meeting.round_number == 1
        assert meeting.event_name == "Test Grand Prix"
        # The circuit is keyed on a slug of the venue, since the provider has
        # no stable circuit id.
        assert meeting.circuit_id is not None

    async def test_marks_the_session_ingested_last(self, connection: AsyncConnection) -> None:  # noqa: F811
        stored = await SessionWriter(connection).store(sample_session())
        ingested_at = (
            await connection.execute(
                select(Session.ingested_at).where(Session.id == stored.session_id)
            )
        ).scalar_one()
        # This flag is what makes the data servable. It must only be set once
        # every row landed.
        assert ingested_at is not None

    async def test_links_drivers_to_their_team_for_the_season(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        season_id = (
            await connection.execute(select(Season.id).where(Season.year == TEST_SEASON))
        ).scalar_one()
        assert await count(connection, DriverSeason, season_id=season_id) == 2


class TestIdempotence:
    """The property the whole design depends on."""

    async def test_storing_twice_does_not_duplicate_rows(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        writer = SessionWriter(connection)
        first = await writer.store(sample_session())
        second = await writer.store(sample_session())

        assert second.session_id == first.session_id
        assert second.meeting_id == first.meeting_id
        assert await count(connection, Lap, session_id=first.session_id) == 4
        assert await count(connection, SessionResult, session_id=first.session_id) == 2
        assert await count(connection, PitStop, session_id=first.session_id) == 1

    async def test_race_control_messages_do_not_accumulate(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # These have no natural key — two identical messages can legitimately
        # occur — so they are replaced wholesale rather than upserted.
        writer = SessionWriter(connection)
        stored = await writer.store(sample_session())
        await writer.store(sample_session())
        assert await count(connection, RaceControlEvent, session_id=stored.session_id) == 2

    async def test_a_correction_upstream_updates_in_place(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # The reason re-ingest exists: a provider fixes a result after the fact.
        writer = SessionWriter(connection)
        stored = await writer.store(sample_session())

        corrected = sample_session(
            results=(
                *[r for r in sample_session().results if r.driver_ref != "norris"],
                type(sample_session().results[1])(
                    driver_ref="norris",
                    position=2,
                    classified_position="2",
                    grid_position=2,
                    points=18.0,
                    status="Disqualified",
                    laps_completed=2,
                ),
            )
        )
        await writer.store(corrected)

        status = (
            await connection.execute(
                select(SessionResult.status)
                .join(Driver, Driver.id == SessionResult.driver_id)
                .where(SessionResult.session_id == stored.session_id)
                .where(Driver.driver_ref == "norris")
            )
        ).scalar_one()
        assert status == "Disqualified"
        assert await count(connection, SessionResult, session_id=stored.session_id) == 2

    async def test_rows_the_provider_dropped_are_removed(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Upserts alone would keep a lap or pit stop that is no longer in the
        # data, so a re-ingest would still serve it.
        writer = SessionWriter(connection)
        full = sample_session()
        stored = await writer.store(full)

        await writer.store(sample_session(laps=full.laps[:2], pit_stops=()))

        assert await count(connection, Lap, session_id=stored.session_id) == 2
        assert await count(connection, PitStop, session_id=stored.session_id) == 0
        assert await count(connection, SessionResult, session_id=stored.session_id) == 2

    async def test_drivers_and_constructors_are_reused(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        writer = SessionWriter(connection)
        await writer.store(sample_session())
        before_drivers = await count(connection, Driver)
        before_teams = await count(connection, Constructor)

        await writer.store(sample_session())

        assert await count(connection, Driver) == before_drivers
        assert await count(connection, Constructor) == before_teams


class TestDerivedValues:
    async def test_fastest_lap_ignores_deleted_laps(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Norris sets the quickest time of the race on lap 2, but it was
        # deleted. Awarding him the fastest lap would contradict the official
        # classification.
        stored = await SessionWriter(connection).store(sample_session())
        row = (
            await connection.execute(
                select(Driver.driver_ref, SessionResult.fastest_lap_time_ms)
                .join(Driver, Driver.id == SessionResult.driver_id)
                .where(SessionResult.session_id == stored.session_id)
                .where(SessionResult.fastest_lap.is_(True))
            )
        ).one()
        assert row.driver_ref == "max_verstappen"
        assert row.fastest_lap_time_ms == 82000

    async def test_race_control_resolves_the_car_number_to_a_driver(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # "CAR 4 TIME DELETED" must attach to Norris, car number 4.
        stored = await SessionWriter(connection).store(sample_session())
        row = (
            await connection.execute(
                select(Driver.driver_ref)
                .join(RaceControlEvent, RaceControlEvent.driver_id == Driver.id)
                .where(RaceControlEvent.session_id == stored.session_id)
            )
        ).one()
        assert row.driver_ref == "norris"

    async def test_session_wide_messages_have_no_driver(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        stored = await SessionWriter(connection).store(sample_session())
        without_driver = (
            await connection.execute(
                select(func.count())
                .select_from(RaceControlEvent)
                .where(RaceControlEvent.session_id == stored.session_id)
                .where(RaceControlEvent.driver_id.is_(None))
            )
        ).scalar_one()
        assert without_driver == 1


class TestPartialSessions:
    async def test_a_partial_session_is_stored_but_not_marked_complete(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Pre-2018 sessions have results but no timing. Storing them is useful;
        # claiming they are complete would serve gaps as though they were true.
        stored = await SessionWriter(connection).store(
            sample_session(laps=(), pit_stops=(), is_partial=True)
        )
        assert stored.is_complete is False

        ingested_at = (
            await connection.execute(
                select(Session.ingested_at).where(Session.id == stored.session_id)
            )
        ).scalar_one()
        assert ingested_at is None
        assert await count(connection, SessionResult, session_id=stored.session_id) == 2

    async def test_a_later_complete_ingest_marks_it_done(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        writer = SessionWriter(connection)
        await writer.store(sample_session(laps=(), pit_stops=(), is_partial=True))
        stored = await writer.store(sample_session())

        ingested_at = (
            await connection.execute(
                select(Session.ingested_at).where(Session.id == stored.session_id)
            )
        ).scalar_one()
        assert ingested_at is not None
        assert await count(connection, Lap, session_id=stored.session_id) == 4
