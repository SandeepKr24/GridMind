"""Stored reports, against Postgres inside a rolled-back transaction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models.enums import ReportTrigger
from app.ingestion.normalizer import SessionWriter
from app.reports import store
from app.reports.writer import Section, WrittenReport
from tests.conftest_db import TEST_SEASON, connection, database, sample_session  # noqa: F401

REPORT = WrittenReport(
    sections=(Section("Race Overview", "Verstappen won."), Section("Key Numbers", "Laps: 2")),
    model="test-model",
)


async def _seeded(connection: AsyncConnection) -> None:  # noqa: F811
    await SessionWriter(connection).store(sample_session())


async def test_a_saved_report_reads_back_by_race_and_by_id(
    connection: AsyncConnection,  # noqa: F811
) -> None:
    await _seeded(connection)

    report_id = await store.save_report(
        connection, TEST_SEASON, 1, REPORT, ReportTrigger.ON_REQUEST
    )
    by_race = await store.report_for_race(connection, TEST_SEASON, 1)
    by_id = await store.report_by_id(connection, report_id)

    assert by_race == by_id
    assert by_race is not None
    assert by_race.event_name == "Test Grand Prix"
    assert by_race.trigger is ReportTrigger.ON_REQUEST
    assert by_race.model == "test-model"
    assert by_race.sections == [
        {"heading": "Race Overview", "body": "Verstappen won."},
        {"heading": "Key Numbers", "body": "Laps: 2"},
    ]


async def test_saving_again_replaces_rather_than_duplicates(
    connection: AsyncConnection,  # noqa: F811
) -> None:
    await _seeded(connection)
    first = await store.save_report(connection, TEST_SEASON, 1, REPORT, ReportTrigger.ON_REQUEST)

    newer = WrittenReport(sections=(Section("Race Overview", "Rewritten."),), model="m2")
    second = await store.save_report(connection, TEST_SEASON, 1, newer, ReportTrigger.AUTOMATIC)

    assert first == second
    assert await store.count_reports(connection, TEST_SEASON) == 1
    stored = await store.report_for_race(connection, TEST_SEASON, 1)
    assert stored is not None
    assert (stored.model, stored.trigger) == ("m2", ReportTrigger.AUTOMATIC)


async def test_counts_latest_and_has_report(
    connection: AsyncConnection,  # noqa: F811
) -> None:
    assert not await store.has_report(connection, TEST_SEASON, 1)
    assert await store.latest_report(connection, TEST_SEASON) is None
    await _seeded(connection)

    await store.save_report(connection, TEST_SEASON, 1, REPORT, ReportTrigger.ON_REQUEST)

    assert await store.has_report(connection, TEST_SEASON, 1)
    assert await store.count_reports(connection, TEST_SEASON) == 1
    latest = await store.latest_report(connection, TEST_SEASON)
    assert latest is not None and latest.round_number == 1


async def test_a_race_that_is_not_stored_cannot_get_a_report(
    connection: AsyncConnection,  # noqa: F811
) -> None:
    try:
        await store.save_report(connection, TEST_SEASON, 99, REPORT, ReportTrigger.ON_REQUEST)
    except LookupError as error:
        assert "not stored" in str(error)
    else:
        raise AssertionError("expected LookupError")


async def test_an_unknown_id_is_none(
    connection: AsyncConnection,  # noqa: F811
) -> None:
    assert await store.report_by_id(connection, 987654321) is None
