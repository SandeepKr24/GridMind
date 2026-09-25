"""Check generated SQL before it reaches the database.

The database is the real safety net: a read-only role, a read-only
transaction, a timeout and an outer LIMIT (`executor.py`). This layer comes
first because a rejection here is cheap and specific. "You may only read
laps, pit_stops, ..." is feedback the model can act on; a permission error
from Postgres is not, and it costs a round trip.

Parsed with sqlglot rather than matched with regexes: a DELETE can hide
inside a CTE, and a table name can appear in a string literal, and only a
parser tells those apart.

Refused:
- anything but exactly one query (SELECT, possibly WITH or UNION);
- any write, DDL, COPY, SET, transaction control, SELECT INTO or row lock,
  wherever it appears in the tree;
- tables outside the six the model is told about, or in another schema;
- functions that sleep, read files, open connections, touch large objects,
  change settings or advance sequences.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

#: The tables described in `sql_generator.SCHEMA_TEXT`, and no others.
ALLOWED_TABLES = frozenset(
    {"session_results", "laps", "pit_stops", "race_control_events", "drivers", "constructors"}
)
ALLOWED_SCHEMAS = frozenset({"", "gridmind"})

#: pg_sleep, pg_read_file, pg_terminate_backend, pg_advisory_lock; lo_create;
#: dblink_*; txid_* all sit behind these prefixes.
BLOCKED_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
BLOCKED_FUNCTIONS = frozenset(
    {
        "set_config",
        # Large-object I/O without the "lo_" prefix.
        "loread",
        "lowrite",
        "nextval",
        "setval",
        "currval",
        "query_to_xml",
        "table_to_xml",
        "cursor_to_xml",
        "schema_to_xml",
        "database_to_xml",
    }
)

#: Node types that mean something other than reading. Looked up by name so a
#: sqlglot release that renames one does not break the import.
_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "TruncateTable",
    "Command",
    "Copy",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    "Grant",
    "Into",
    "Lock",
)
FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = tuple(
    node for name in _FORBIDDEN_NODE_NAMES if isinstance(node := getattr(exp, name, None), type)
)


class SqlRejectedError(ValueError):
    """The query is not allowed. The message is written for the model to fix it."""


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _parse_one(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as error:
        first = str(error).strip().splitlines()[0] if str(error).strip() else "parse error"
        raise SqlRejectedError(f"the query could not be parsed: {first}") from error
    if len(statements) != 1:
        raise SqlRejectedError("write exactly one SELECT statement")
    return statements[0]


def _check_tables(root: exp.Expr) -> None:
    ctes = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        name = table.name.lower()
        if not name:
            continue  # a table function such as generate_series; checked below
        if table.db.lower() not in ALLOWED_SCHEMAS:
            raise SqlRejectedError(f"table {table.db}.{name} is not available")
        if name not in ALLOWED_TABLES and name not in ctes:
            allowed = ", ".join(sorted(ALLOWED_TABLES))
            raise SqlRejectedError(f"table {name} is not available; use only {allowed}")


def _check_functions(root: exp.Expr) -> None:
    for function in root.find_all(exp.Func):
        name = _function_name(function)
        if name.startswith(BLOCKED_PREFIXES) or name in BLOCKED_FUNCTIONS:
            raise SqlRejectedError(f"function {name} is not allowed")
    # 'pg_authid'::regclass looks up a system object without naming a table
    # or calling a function. No F1 question needs an object-identifier type.
    for cast in root.find_all(exp.Cast):
        target = cast.to.sql(dialect="postgres").lower()
        if target.startswith("reg"):
            raise SqlRejectedError(f"casting to {target} is not allowed")


def validate_sql(sql: str) -> None:
    """Raise `SqlRejectedError` unless `sql` is one plain read of our tables."""
    root = _parse_one(sql)
    if not isinstance(root, exp.Query):
        raise SqlRejectedError("only a SELECT query is allowed")
    forbidden = next(root.find_all(*FORBIDDEN_NODES), None) if FORBIDDEN_NODES else None
    if forbidden is not None:
        raise SqlRejectedError(
            f"only reading is allowed; remove the {type(forbidden).__name__.upper()}"
        )
    _check_tables(root)
    _check_functions(root)
