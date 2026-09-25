"""Running generated SQL: the read-only role, the timeout, the row cap, the values.

The database tests run as the real read-only role against Neon, because the
guarantees here are the database's, not ours. None of them writes: the one
write attempt is refused before it reaches a row.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json

import pytest

from app.agent.executor import (
    PostgresQueryRunner,
    QueryFailedError,
    bounded,
    escape_percent,
    to_json_value,
)
from app.db.database import Database
from tests.conftest_db import database  # noqa: F401


class TestValues:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            (True, True),
            (7, 7),
            ("VER", "VER"),
            (1.5, 1.5),
            (float("nan"), None),
            (decimal.Decimal("25"), 25),
            (decimal.Decimal("12.50"), 12.5),
            (dt.date(2024, 7, 28), "2024-07-28"),
            (dt.datetime(2024, 7, 28, 13, 0, tzinfo=dt.UTC), "2024-07-28T13:00:00+00:00"),
            (dt.timedelta(seconds=1, milliseconds=500), 1500),
        ],
    )
    def test_values_become_json_safe(self, value: object, expected: object) -> None:
        assert to_json_value(value) == expected

    def test_arrays_and_objects_become_json_not_python_reprs(self) -> None:
        # Seen live: json_agg came back as "['HARD', 'MEDIUM']".
        assert json.loads(str(to_json_value(["HARD", "MEDIUM"]))) == ["HARD", "MEDIUM"]
        assert json.loads(str(to_json_value({"laps": 3}))) == {"laps": 3}

    def test_queries_are_wrapped_in_an_outer_limit(self) -> None:
        assert bounded("SELECT 1 -- note", 51) == (
            "SELECT * FROM (\nSELECT 1 -- note\n) AS agent_query LIMIT 51"
        )

    def test_percent_signs_are_doubled_for_psycopg(self) -> None:
        assert escape_percent("message ILIKE '%penalty%'") == "message ILIKE '%%penalty%%'"


class TestSingleStatement:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1; SET statement_timeout = 0",
            "SELECT 1; DELETE FROM laps",
            "SELECT ';'",
        ],
    )
    async def test_anything_after_a_semicolon_is_refused_before_the_database(
        self, sql: str
    ) -> None:
        runner = PostgresQueryRunner(database=None)  # type: ignore[arg-type]

        with pytest.raises(QueryFailedError, match="only one statement"):
            await runner.run(sql)


class TestAgainstPostgres:
    async def test_rows_columns_and_timing_come_back(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        result = await PostgresQueryRunner(database).run(
            "SELECT 1 AS one, 'two' AS two, 2.50::numeric AS three;"
        )

        assert result.columns == ("one", "two", "three")
        assert result.rows == ((1, "two", 2.5),)
        assert not result.truncated
        assert result.elapsed_ms >= 0

    async def test_percent_and_colon_survive(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        result = await PostgresQueryRunner(database).run(
            "SELECT 'x penalty y' ILIKE '%penalty%' AS hit, ':word' AS colon, 3::int AS cast"
        )

        assert result.rows == ((True, ":word", 3),)

    async def test_rows_beyond_the_cap_are_cut_and_flagged(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        result = await PostgresQueryRunner(database, max_rows=5).run(
            "SELECT n FROM generate_series(1, 60) AS n"
        )

        assert len(result.rows) == 5
        assert result.truncated

    async def test_the_server_never_sends_more_than_the_cap(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        # Would be ~10^12 rows; the outer LIMIT stops it at the server.
        result = await PostgresQueryRunner(database, max_rows=3).run(
            "SELECT a.n FROM generate_series(1, 1000000) a(n) "
            "CROSS JOIN generate_series(1, 1000000) b(n) -- trailing comment"
        )

        assert len(result.rows) == 3
        assert result.truncated

    async def test_statements_that_are_not_queries_cannot_run(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        with pytest.raises(QueryFailedError):
            await PostgresQueryRunner(database).run("SET statement_timeout = 0")

    async def test_the_querys_own_order_survives_the_wrapper(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        # Rankings depend on it: "who was fastest" is ORDER BY ... LIMIT.
        result = await PostgresQueryRunner(database, max_rows=5).run(
            "SELECT n FROM generate_series(1, 1000) AS n ORDER BY n DESC"
        )

        assert [row[0] for row in result.rows] == [1000, 999, 998, 997, 996]

    async def test_an_empty_result_is_not_an_error(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        result = await PostgresQueryRunner(database).run("SELECT 1 WHERE false")

        assert result.is_empty

    async def test_a_write_is_refused_by_the_database(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        # Refused before read-only mode is even consulted: a DELETE cannot sit
        # inside the outer SELECT, and neither can a data-modifying WITH.
        runner = PostgresQueryRunner(database)
        with pytest.raises(QueryFailedError):
            await runner.run("DELETE FROM laps WHERE false")
        with pytest.raises(QueryFailedError, match="data-modifying"):
            await runner.run("WITH gone AS (DELETE FROM laps WHERE false RETURNING 1) SELECT 1")

    async def test_a_write_hidden_in_a_function_meets_the_read_only_transaction(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        # A SELECT, so the outer wrapper allows it; the transaction does not.
        with pytest.raises(QueryFailedError, match="read-only"):
            await PostgresQueryRunner(database).run("SELECT lo_create(0)")

    async def test_a_slow_query_is_cancelled(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        with pytest.raises(QueryFailedError, match="statement timeout"):
            await PostgresQueryRunner(database, timeout_ms=100).run("SELECT pg_sleep(2)")

    async def test_a_bad_query_reports_the_database_error_briefly(
        self,
        database: Database,  # noqa: F811
    ) -> None:
        with pytest.raises(QueryFailedError) as caught:
            await PostgresQueryRunner(database).run("SELECT no_such_column FROM laps")

        assert "no_such_column" in str(caught.value)
        assert "\n" not in str(caught.value)
