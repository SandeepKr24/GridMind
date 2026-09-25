"""Run a generated query as safely as the database allows.

Four layers, from the outside in:

1. the read-only role, which has SELECT grants and nothing else;
2. `default_transaction_read_only`, set on every reader connection;
3. an explicit `SET TRANSACTION READ ONLY` here, so the refusal does not
   depend on connection settings someone might change later;
4. a per-query `statement_timeout`, so a runaway join is cancelled rather
   than holding Neon's compute awake;

and two guards on the text itself: a single statement only, so nothing can
follow the query and lift that timeout; and an outer LIMIT, so the server
never sends more rows than the cap.

Statement-level validation of the SQL text is the next layer up
(`sql_validator.py`, step 15). This module assumes nothing about the query.
Rows are capped in Python as well as by LIMIT, and every value is turned into
something JSON can carry.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.database import Database

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 5_000
MAX_ROWS = 50
#: Postgres error text goes back to the model on a retry; keep it bounded.
MAX_ERROR_TEXT = 300

JsonValue = str | int | float | bool | None


class QueryFailedError(RuntimeError):
    """The database rejected or cancelled the query. The text is safe to show the model."""


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[JsonValue, ...], ...]
    #: More rows existed than MAX_ROWS; the answer must not claim completeness.
    truncated: bool
    elapsed_ms: int

    @property
    def is_empty(self) -> bool:
        return not self.rows


class QueryRunner(Protocol):
    async def run(self, sql: str) -> QueryResult: ...


def to_json_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if value == value else None  # NaN has no JSON form
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return round(value.total_seconds() * 1000)
    if isinstance(value, list | tuple | dict):
        # json_agg and arrays; str() would give a Python repr.
        return json.dumps(value, default=str)
    return str(value)


def bounded(sql: str, limit: int) -> str:
    """The query wrapped so the server returns at most `limit` rows.

    psycopg's default cursor reads the whole result into memory during
    execute(), so capping with fetchmany alone would still let a cross join
    exhaust memory inside the timeout. Wrapping also means only a query can
    run: COPY or SET cannot sit inside a subquery. The newline keeps a
    trailing "-- comment" from swallowing the closing parenthesis.

    The inner ORDER BY is kept: with nothing but a LIMIT on top, Postgres
    returns the subquery's rows in its own order. `test_executor.py` pins
    this, because every "who was fastest" answer depends on it.
    """
    return f"SELECT * FROM (\n{sql}\n) AS agent_query LIMIT {int(limit)}"


def escape_percent(sql: str) -> str:
    return sql.replace("%", "%%")


def _first_line(error: DBAPIError) -> str:
    original = getattr(error, "orig", None) or error
    lines = str(original).strip().splitlines()
    return (lines[0] if lines else type(error).__name__)[:MAX_ERROR_TEXT]


class PostgresQueryRunner:
    def __init__(
        self,
        database: Database,
        *,
        timeout_ms: int = STATEMENT_TIMEOUT_MS,
        max_rows: int = MAX_ROWS,
    ) -> None:
        self._db = database
        self._timeout_ms = timeout_ms
        self._max_rows = max_rows

    async def run(self, sql: str) -> QueryResult:
        if ";" in sql.strip().rstrip(";"):
            # One call may carry several statements when there are no bind
            # parameters, and "...; SET statement_timeout = 0" would lift the
            # cap below. A semicolon inside a string literal is refused too;
            # that costs one regeneration, which is cheap.
            raise QueryFailedError("only one statement is allowed; remove the semicolons")
        sql = sql.strip().rstrip(";")
        started = time.monotonic()
        try:
            async with self._db.reader.connect() as connection, connection.begin():
                # SET LOCAL takes no bind parameters; the value is our own int.
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(
                    text(f"SET LOCAL statement_timeout = {int(self._timeout_ms)}")
                )
                # Raw driver SQL: text() would read ":word" as a bind parameter.
                # SQLAlchemy still hands psycopg an (empty) parameter list, so a
                # literal "%" in LIKE '%penalty%' must be doubled. Having
                # parameters also puts psycopg on the extended protocol, which
                # refuses a second statement outright.
                result = await connection.exec_driver_sql(
                    escape_percent(bounded(sql, self._max_rows + 1))
                )
                columns = tuple(result.keys())
                fetched = result.fetchmany(self._max_rows + 1)
        except DBAPIError as error:
            message = _first_line(error)
            logger.warning("agent query failed: %s", message)
            raise QueryFailedError(message) from error

        elapsed_ms = round((time.monotonic() - started) * 1000)
        rows = tuple(tuple(to_json_value(v) for v in row) for row in fetched[: self._max_rows])
        logger.info("agent query rows=%d elapsed_ms=%d sql=%s", len(rows), elapsed_ms, sql)
        return QueryResult(columns, rows, len(fetched) > self._max_rows, elapsed_ms)
