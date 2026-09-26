"""Reports in Postgres: written once on the writer role, read on the reader.

One full report per race weekend. The table's unique constraint on
(meeting, report type) means a regenerated report replaces the old one
instead of piling up near-copies. Nothing regenerates one unasked: it is the
most token-expensive thing the system does.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.analytics import race_stats
from app.db.database import Database
from app.db.models import Meeting, Report, Season
from app.db.models.enums import ReportTrigger, ReportType
from app.reports.facts import ReportFacts, build_facts
from app.reports.writer import WrittenReport


@dataclass(frozen=True, slots=True)
class StoredReport:
    id: int
    season: int
    round_number: int
    event_name: str
    report_type: ReportType
    trigger: ReportTrigger
    model: str | None
    generated_at: dt.datetime
    sections: list[dict[str, Any]]


def _reports() -> Any:
    return (
        select(
            Report.id,
            Season.year,
            Meeting.round_number,
            Meeting.event_name,
            Report.report_type,
            Report.trigger,
            Report.model,
            Report.generated_at,
            Report.sections,
        )
        .join(Meeting, Meeting.id == Report.meeting_id)
        .join(Season, Season.id == Meeting.season_id)
        .where(Report.report_type == ReportType.FULL)
    )


def _stored(row: Any) -> StoredReport:
    return StoredReport(
        id=row.id,
        season=row.year,
        round_number=row.round_number,
        event_name=row.event_name,
        report_type=row.report_type,
        trigger=row.trigger,
        model=row.model,
        generated_at=row.generated_at,
        sections=list(row.sections or []),
    )


async def report_for_race(
    connection: AsyncConnection, season: int, round_number: int
) -> StoredReport | None:
    statement = _reports().where(Season.year == season, Meeting.round_number == round_number)
    row = (await connection.execute(statement)).first()
    return _stored(row) if row else None


async def report_by_id(connection: AsyncConnection, report_id: int) -> StoredReport | None:
    row = (await connection.execute(_reports().where(Report.id == report_id))).first()
    return _stored(row) if row else None


async def latest_report(connection: AsyncConnection, season: int) -> StoredReport | None:
    statement = _reports().where(Season.year == season).order_by(Report.generated_at.desc())
    row = (await connection.execute(statement.limit(1))).first()
    return _stored(row) if row else None


async def count_reports(connection: AsyncConnection, season: int) -> int:
    statement = (
        select(func.count(Report.id))
        .join(Meeting, Meeting.id == Report.meeting_id)
        .join(Season, Season.id == Meeting.season_id)
        .where(Season.year == season, Report.report_type == ReportType.FULL)
    )
    return int(await connection.scalar(statement) or 0)


async def has_report(connection: AsyncConnection, season: int, round_number: int) -> bool:
    return await report_for_race(connection, season, round_number) is not None


async def save_report(
    connection: AsyncConnection,
    season: int,
    round_number: int,
    report: WrittenReport,
    trigger: ReportTrigger,
) -> int:
    """Store the report for the race, replacing any earlier one. Returns its id."""
    meeting_id = await connection.scalar(
        select(Meeting.id)
        .join(Season, Season.id == Meeting.season_id)
        .where(Season.year == season, Meeting.round_number == round_number)
    )
    if meeting_id is None:
        raise LookupError(f"{season} round {round_number} is not stored")
    values = {
        "meeting_id": meeting_id,
        "report_type": ReportType.FULL,
        "trigger": trigger,
        "content": report.content(),
        "sections": [{"heading": s.heading, "body": s.body} for s in report.sections],
        "model": report.model,
        "generated_at": func.now(),
    }
    statement = (
        insert(Report)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[Report.meeting_id, Report.report_type],
            set_={k: v for k, v in values.items() if k not in ("meeting_id", "report_type")},
        )
        .returning(Report.id)
    )
    report_id = await connection.scalar(statement)
    assert report_id is not None
    return int(report_id)


class PostgresReportArchive:
    """`ReportArchive` for the job runner: reads on the reader, writes on the writer."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def exists(self, season: int, round_number: int) -> bool:
        async with self._db.connect(read_only=True) as connection:
            return await has_report(connection, season, round_number)

    async def save(
        self, season: int, round_number: int, report: WrittenReport, trigger: ReportTrigger
    ) -> int:
        async with self._db.writer.begin() as connection:
            return await save_report(connection, season, round_number, report, trigger)


class PostgresFactsSource:
    """`FactsSource`: the race page's own analytics, on the reader."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self, season: int, round_number: int) -> ReportFacts:
        async with self._db.connect(read_only=True) as connection:
            race = await race_stats.get_race(connection, season, round_number)
            stats = await race_stats.get_race_stats(connection, season, round_number)
        return build_facts(race, stats)
