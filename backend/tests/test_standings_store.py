"""Standings rows against the real database, in rolled-back transactions."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Driver
from app.ingestion import standings_store as store
from app.ingestion.normalizer import SessionWriter
from app.ingestion.standings_provider import (
    RawConstructorStanding,
    RawDriverStanding,
    RawStandings,
)
from tests.conftest_db import (  # noqa: F401
    TEST_SEASON,
    connection,
    database,
    sample_session,
)

pytestmark = pytest.mark.asyncio

VERSTAPPEN = RawDriverStanding(
    driver_ref="max_verstappen",
    code="VER",
    first_name="Max",
    last_name="Verstappen",
    full_name="Max Verstappen",
    nationality="Dutch",
    permanent_number=3,
    constructor_ref="red_bull",
    constructor_name="Red Bull",
    position=1,
    points=437.0,
    wins=9,
)
NEWCOMER = RawDriverStanding(
    driver_ref="gridmind_test_rookie",
    code="ROO",
    first_name="Test",
    last_name="Rookie",
    full_name="Test Rookie",
    nationality=None,
    permanent_number=None,
    constructor_ref="gridmind_test_team",
    constructor_name="Test Team",
    position=2,
    points=374.5,
    wins=4,
)
TEAM = RawConstructorStanding(
    constructor_ref="gridmind_test_team",
    name="Test Team",
    nationality=None,
    position=1,
    points=666.0,
    wins=6,
)


def standings(round_number: int = 5, **overrides: object) -> RawStandings:
    fields: dict[str, object] = {
        "season": TEST_SEASON,
        "round_number": round_number,
        "drivers": (VERSTAPPEN, NEWCOMER),
        "constructors": (TEAM,),
    }
    fields.update(overrides)
    return RawStandings(**fields)  # type: ignore[arg-type]


class TestFreshness:
    async def test_a_season_never_fetched_has_no_record(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        assert await store.latest_fetch(connection, TEST_SEASON) is None

    async def test_saving_records_when_and_which_round(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await store.save(connection, standings(round_number=5))

        fetch = await store.latest_fetch(connection, TEST_SEASON)

        assert fetch is not None
        assert fetch.round_number == 5
        assert fetch.fetched_at is not None

    async def test_an_empty_season_is_still_recorded(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # Otherwise a season with no races yet would be refetched every time.
        await store.save(connection, standings(round_number=0, drivers=(), constructors=()))
        fetch = await store.latest_fetch(connection, TEST_SEASON)
        assert fetch is not None
        assert fetch.round_number == 0


class TestDrivers:
    async def test_reads_back_in_championship_order(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await store.save(connection, standings(drivers=(NEWCOMER, VERSTAPPEN)))

        rows = await store.read_drivers(connection, TEST_SEASON)

        assert [(r.position, r.driver_name, r.points) for r in rows] == [
            (1, "Max Verstappen", 437.0),
            (2, "Test Rookie", 374.5),
        ]
        assert (rows[1].driver_code, rows[1].constructor_name, rows[1].wins) == (
            "ROO",
            "Test Team",
            4,
        )

    async def test_only_the_latest_round_is_read(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await store.save(connection, standings(round_number=4))
        later = dataclasses.replace(VERSTAPPEN, points=500.0)
        await store.save(connection, standings(round_number=5, drivers=(later,)))

        rows = await store.read_drivers(connection, TEST_SEASON)

        assert [(r.driver_name, r.points) for r in rows] == [("Max Verstappen", 500.0)]

    async def test_refreshing_the_same_round_updates_in_place(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # jolpica corrects results after stewards' decisions.
        await store.save(connection, standings())
        corrected = dataclasses.replace(NEWCOMER, points=370.0)
        await store.save(connection, standings(drivers=(VERSTAPPEN, corrected)))

        rows = await store.read_drivers(connection, TEST_SEASON)
        assert [r.points for r in rows] == [437.0, 370.0]

    async def test_an_excluded_driver_sorts_last(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        excluded = dataclasses.replace(NEWCOMER, position=None, points=0.0)
        await store.save(connection, standings(drivers=(excluded, VERSTAPPEN)))

        rows = await store.read_drivers(connection, TEST_SEASON)
        assert [r.position for r in rows] == [1, None]

    async def test_ingested_driver_details_are_not_overwritten(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        # FastF1 is the richer source for identity; jolpica only adds rows.
        await SessionWriter(connection).store(sample_session())
        before = (
            await connection.execute(
                select(Driver.full_name, Driver.nationality).where(
                    Driver.driver_ref == "max_verstappen"
                )
            )
        ).one()

        await store.save(connection, standings())

        after = (
            await connection.execute(
                select(Driver.full_name, Driver.nationality).where(
                    Driver.driver_ref == "max_verstappen"
                )
            )
        ).one()
        assert after == before

    async def test_an_unfetched_season_reads_empty(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        assert await store.read_drivers(connection, TEST_SEASON) == []


class TestConstructors:
    async def test_reads_back(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await store.save(connection, standings())

        rows = await store.read_constructors(connection, TEST_SEASON)

        assert [(r.position, r.constructor_name, r.points, r.wins) for r in rows] == [
            (1, "Test Team", 666.0, 6)
        ]
