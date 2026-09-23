"""Structural guarantees of the schema.

These run against the model metadata, so they need no database. They cover the
properties that would be expensive to discover later: the concurrency guard on
ingestion jobs, the unique constraints that make re-ingestion idempotent, and
the placement of every table in the `gridmind` schema rather than `public`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Integer, SmallInteger

from app.db.models import SCHEMA, Base, IngestionJob, Lap, Session, SessionResult
from app.db.models.enums import ACTIVE_STATUSES, JobStatus

TABLES = Base.metadata.tables


class TestSchemaPlacement:
    def test_every_table_lives_in_the_gridmind_schema(self) -> None:
        # Not public: the read-only role has no access to public at all, so a
        # table landing there would be invisible to the agent.
        assert SCHEMA == "gridmind"
        wrong = [t.fullname for t in TABLES.values() if t.schema != SCHEMA]
        assert wrong == []

    def test_expected_tables_exist(self) -> None:
        names = {t.name for t in TABLES.values()}
        assert names == {
            "seasons",
            "circuits",
            "meetings",
            "sessions",
            "drivers",
            "constructors",
            "driver_seasons",
            "session_results",
            "laps",
            "pit_stops",
            "race_control_events",
            "driver_standings",
            "constructor_standings",
            "standings_fetches",
            "reports",
            "ingestion_jobs",
        }


class TestIngestionJobConcurrencyGuard:
    """The single most important constraint in the schema."""

    def _guard(self) -> object:
        table = TABLES[f"{SCHEMA}.ingestion_jobs"]
        return next(i for i in table.indexes if i.name == "uq_ingestion_jobs_active")

    def test_the_guard_exists_and_is_unique(self) -> None:
        assert self._guard().unique is True  # type: ignore[attr-defined]

    def test_it_covers_the_session_identity(self) -> None:
        columns = [c.name for c in self._guard().columns]  # type: ignore[attr-defined]
        assert columns == ["season_year", "round_number", "session_type"]

    def test_it_is_partial_so_finished_jobs_do_not_block_new_ones(self) -> None:
        # Without the WHERE clause, one completed job would permanently
        # prevent that session from ever being re-ingested.
        where = self._guard().dialect_options["postgresql"]["where"]  # type: ignore[attr-defined]
        assert where is not None
        assert "pending" in str(where)
        assert "running" in str(where)

    def test_the_guard_literals_match_active_statuses(self) -> None:
        # The index hard-codes status literals in SQL. If someone adds a third
        # active status to the enum without touching the index, two ingestions
        # of one session could run at once.
        where = str(self._guard().dialect_options["postgresql"]["where"])  # type: ignore[attr-defined]
        for status in ACTIVE_STATUSES:
            assert f"'{status.value}'" in where
        for status in set(JobStatus) - ACTIVE_STATUSES:
            assert f"'{status.value}'" not in where

    def test_job_id_is_a_string_the_frontend_can_carry_in_a_url(self) -> None:
        # The frontend validates ?job= against ^[A-Za-z0-9_-]{1,64}$.
        assert IngestionJob.__table__.c.id.type.length == 64


class TestIdempotentIngestion:
    """Asking for the same session twice must update, not duplicate."""

    @pytest.mark.parametrize(
        ("table", "expected"),
        [
            ("sessions", {"meeting_id", "session_type"}),
            ("meetings", {"season_id", "round_number"}),
            ("session_results", {"session_id", "driver_id"}),
            ("laps", {"session_id", "driver_id", "lap_number"}),
            ("pit_stops", {"session_id", "driver_id", "stop_number"}),
            ("reports", {"meeting_id", "report_type"}),
            ("driver_standings", {"season_id", "round_number", "driver_id"}),
        ],
    )
    def test_natural_key_is_unique(self, table: str, expected: set[str]) -> None:
        constraints = TABLES[f"{SCHEMA}.{table}"].constraints
        unique_sets = [
            {c.name for c in con.columns}
            for con in constraints
            if con.__class__.__name__ == "UniqueConstraint"
        ]
        assert expected in unique_sets


class TestPostgresEnumLabels:
    """A bug this caught, and must keep catching.

    SQLAlchemy's `Enum(SomeEnum)` defaults to storing member **names**, so the
    first migration created Postgres types with labels `PRACTICE_1` and `RACE`
    while the application and the frontend speak `practice_1` and `race`. There
    is no compile-time symptom; it fails on the first insert, or silently
    disagrees with the wire contract.
    """

    @pytest.mark.parametrize(
        ("table", "column", "expected"),
        [
            ("sessions", "session_type", "practice_1"),
            ("ingestion_jobs", "session_type", "race"),
            ("ingestion_jobs", "status", "skipped_cached"),
            ("ingestion_jobs", "stage", "answering"),
            ("reports", "report_type", "summary"),
            ("reports", "trigger", "on_request"),
        ],
    )
    def test_labels_are_values_not_member_names(
        self, table: str, column: str, expected: str
    ) -> None:
        enum_type = TABLES[f"{SCHEMA}.{table}"].c[column].type
        assert expected in enum_type.enums  # type: ignore[attr-defined]
        assert expected.upper() not in enum_type.enums  # type: ignore[attr-defined]

    def test_enum_types_live_in_the_gridmind_schema(self) -> None:
        # Created unqualified, they land in `public`, which the read-only role
        # cannot see. Reading the column still works, but any SQL naming the
        # type fails with `type "session_type" does not exist` — and the agent
        # writes its own SQL.
        for table in TABLES.values():
            for column in table.c:
                if getattr(column.type, "enums", None):
                    assert column.type.schema == SCHEMA, (  # type: ignore[attr-defined]
                        f"{table.name}.{column.name} type is not in {SCHEMA}"
                    )

    def test_every_enum_column_uses_lowercase_labels(self) -> None:
        # A sweep, so a new enum column added later cannot reintroduce this.
        for table in TABLES.values():
            for column in table.c:
                labels = getattr(column.type, "enums", None)
                if labels:
                    assert all(label.islower() for label in labels), (
                        f"{table.name}.{column.name} stores names, not values: {labels}"
                    )


class TestCacheFlag:
    def test_ingested_at_is_nullable_and_indexed(self) -> None:
        # Null means "not stored yet", which is what triggers an ingestion job.
        # It is indexed because every race listing filters on it.
        column = Session.__table__.c.ingested_at
        assert column.nullable is True
        indexed = {tuple(c.name for c in i.columns) for i in Session.__table__.indexes}
        assert ("ingested_at",) in indexed


class TestDurations:
    @pytest.mark.parametrize(
        ("model", "column"),
        [
            (Lap, "lap_time_ms"),
            (Lap, "sector_1_ms"),
            (SessionResult, "fastest_lap_time_ms"),
            (SessionResult, "q1_time_ms"),
        ],
    )
    def test_times_are_integer_milliseconds(self, model: type, column: str) -> None:
        # Integers so the agent's SUM/AVG/MIN behave predictably.
        assert isinstance(model.__table__.c[column].type, Integer | SmallInteger)

    def test_lap_time_is_nullable_for_in_and_out_laps(self) -> None:
        # Storing 0 would drag every average down.
        assert Lap.__table__.c.lap_time_ms.nullable is True

    def test_qualifying_segment_times_live_on_the_result_row(self) -> None:
        columns = SessionResult.__table__.c
        assert {"q1_time_ms", "q2_time_ms", "q3_time_ms"} <= set(columns.keys())
        assert all(columns[f"q{n}_time_ms"].nullable for n in (1, 2, 3))
