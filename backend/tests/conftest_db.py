"""Database fixtures for integration tests.

Every test runs inside a transaction that is rolled back afterwards, so the
suite can use the real Neon database without leaving anything behind and
without tests seeing each other's rows.

Mocking SQLAlchemy here would test nothing: the whole point of the normalizer
is what Postgres does with `ON CONFLICT`, unique constraints and foreign keys.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import Settings
from app.db.database import Database
from app.db.models.enums import SessionType
from app.ingestion.base import (
    RawDriverEntry,
    RawEvent,
    RawLap,
    RawPitStop,
    RawRaceControlMessage,
    RawResult,
    RawSession,
)
from app.runtime import configure_event_loop

configure_event_loop()


def _settings() -> Settings | None:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:
        return None


@pytest_asyncio.fixture(scope="session")
async def database() -> AsyncIterator[Database]:
    """One engine for the whole suite.

    Session-scoped because a fresh TLS handshake to Neon per test costs more
    than every assertion in this file put together.
    """
    settings = _settings()
    if settings is None:
        pytest.skip("no database configured (backend/.env missing)")

    instance = Database(settings)
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest_asyncio.fixture
async def connection(database: Database) -> AsyncIterator[AsyncConnection]:
    """A connection in a transaction that is always rolled back.

    Nothing a test writes survives it, so the tests are order-independent and
    leave the real database untouched.
    """
    async with database.writer.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


# -- sample payloads ---------------------------------------------------
#
# Shaped like real FastF1 output, kept small enough to assert on exactly.
# The season is far in the future so these rows cannot collide with anything
# a real ingest might have stored.

TEST_SEASON = 2099

VERSTAPPEN = RawDriverEntry(
    driver_ref="max_verstappen",
    code="VER",
    number=1,
    first_name="Max",
    last_name="Verstappen",
    full_name="Max Verstappen",
    nationality="NED",
    constructor_ref="red_bull",
    constructor_name="Red Bull Racing",
)
NORRIS = RawDriverEntry(
    driver_ref="norris",
    code="NOR",
    number=4,
    first_name="Lando",
    last_name="Norris",
    full_name="Lando Norris",
    nationality="GBR",
    constructor_ref="mclaren",
    constructor_name="McLaren",
)

EVENT = RawEvent(
    season=TEST_SEASON,
    round_number=1,
    event_name="Test Grand Prix",
    official_name="FORMULA 1 TEST GRAND PRIX",
    event_date=dt.date(TEST_SEASON, 3, 1),
    country="Testland",
    location="Test Circuit",
    event_format="conventional",
    sessions=(SessionType.RACE,),
)


def sample_session(**overrides: object) -> RawSession:
    payload: dict[str, object] = {
        "event": EVENT,
        "session_type": SessionType.RACE,
        "session_date": dt.datetime(TEST_SEASON, 3, 1, 14, 0, tzinfo=dt.UTC),
        "drivers": (VERSTAPPEN, NORRIS),
        "results": (
            RawResult(
                driver_ref="max_verstappen",
                position=1,
                classified_position="1",
                grid_position=1,
                points=25.0,
                status="Finished",
                laps_completed=2,
            ),
            RawResult(
                driver_ref="norris",
                position=2,
                classified_position="2",
                grid_position=2,
                points=18.0,
                status="Finished",
                laps_completed=2,
            ),
        ),
        "laps": (
            _lap("max_verstappen", 1, 83000),
            _lap("max_verstappen", 2, 82000),
            _lap("norris", 1, 84000),
            # Norris sets the quickest time of the race, but it was deleted.
            _lap("norris", 2, 81000, deleted=True),
        ),
        "pit_stops": (
            RawPitStop(driver_ref="max_verstappen", stop_number=1, lap_number=1, duration_ms=23000),
        ),
        "race_control": (
            RawRaceControlMessage(
                message="GREEN LIGHT - PIT EXIT OPEN",
                timestamp=dt.datetime(TEST_SEASON, 3, 1, 13, 50, tzinfo=dt.UTC),
                lap_number=1,
                category="Flag",
                flag="GREEN",
                scope="Track",
                driver_number=None,
            ),
            RawRaceControlMessage(
                message="CAR 4 TIME DELETED - TRACK LIMITS",
                timestamp=dt.datetime(TEST_SEASON, 3, 1, 14, 30, tzinfo=dt.UTC),
                lap_number=2,
                category="Other",
                flag=None,
                scope="Driver",
                driver_number=4,
            ),
        ),
    }
    payload.update(overrides)
    return RawSession(**payload)  # type: ignore[arg-type]


def _lap(driver_ref: str, number: int, time_ms: int, *, deleted: bool = False) -> RawLap:
    return RawLap(
        driver_ref=driver_ref,
        lap_number=number,
        lap_time_ms=time_ms,
        sector_1_ms=None,
        sector_2_ms=None,
        sector_3_ms=None,
        speed_trap_kph=310.0,
        position=1,
        compound="MEDIUM",
        tyre_life=number,
        is_personal_best=False,
        track_status="1",
        is_deleted=deleted,
    )
