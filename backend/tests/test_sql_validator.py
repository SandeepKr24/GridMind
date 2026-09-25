"""The SQL validator: what the model may run, and what it is told when it may not."""

from __future__ import annotations

import pytest

from app.agent.sql_validator import FORBIDDEN_NODES, SqlRejectedError, validate_sql

# Every query the model wrote in the live runs of step 14. All must pass.
REAL_QUERIES = [
    "SELECT d.full_name, c.name FROM session_results sr JOIN drivers d ON sr.driver_id = d.id "
    "JOIN constructors c ON sr.constructor_id = c.id WHERE sr.session_id = 1 AND sr.position = 1 "
    "LIMIT 50",
    "WITH driver_laps AS (SELECT driver_id, AVG(lap_time_ms) AS avg_lap_time_ms FROM laps "
    "WHERE session_id = 1 AND driver_id IN (5,3) AND lap_time_ms IS NOT NULL AND "
    "track_status = '1' GROUP BY driver_id) SELECT d.full_name, dl.avg_lap_time_ms FROM "
    "driver_laps dl JOIN drivers d ON d.id = dl.driver_id ORDER BY dl.avg_lap_time_ms LIMIT 50",
    "SELECT d.full_name, c.name, (sr.grid_position - sr.position) AS positions_gained FROM "
    "session_results sr JOIN drivers d ON sr.driver_id = d.id JOIN constructors c ON "
    "sr.constructor_id = c.id WHERE sr.session_id = 136 AND sr.position IS NOT NULL AND "
    "(sr.grid_position - sr.position) > 0 ORDER BY positions_gained DESC LIMIT 1",
    "SELECT COUNT(*) AS safety_car_count FROM race_control_events WHERE session_id = 136 "
    "AND category = 'SafetyCar'",
    "SELECT DISTINCT d.full_name FROM race_control_events r JOIN drivers d ON r.driver_id = "
    "d.id WHERE r.session_id = 1 AND r.category = 'Other' AND (r.message ILIKE '%DELETED%' "
    "OR r.message ILIKE '%PENALTY%') LIMIT 50",
    "WITH compounds AS (SELECT json_agg(DISTINCT compound) AS compounds FROM laps WHERE "
    "session_id = 136 AND driver_id = 4 AND compound IS NOT NULL), pit AS (SELECT "
    "json_agg(DISTINCT lap_number) AS pit_laps FROM pit_stops WHERE session_id = 136 AND "
    "driver_id = 4) SELECT c.compounds, p.pit_laps FROM compounds c CROSS JOIN pit p LIMIT 50",
]


class TestAllowed:
    @pytest.mark.parametrize("sql", REAL_QUERIES)
    def test_every_query_seen_live_passes(self, sql: str) -> None:
        validate_sql(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1 UNION ALL SELECT 2",
            "SELECT n FROM generate_series(1, 5) AS n",
            "SELECT * FROM gridmind.laps WHERE session_id = 1",
            "SELECT lap_number, lap_time_ms - LAG(lap_time_ms) OVER (ORDER BY lap_number) "
            "FROM laps WHERE session_id = 1",
            "SELECT 'pg_sleep(10) and DELETE FROM laps' AS text_only",
            "SELECT count(*) FILTER (WHERE compound = 'SOFT') FROM laps",
            "SELECT 1;",
        ],
    )
    def test_ordinary_reads_pass(self, sql: str) -> None:
        validate_sql(sql)


class TestRejected:
    @pytest.mark.parametrize(
        ("sql", "reason"),
        [
            ("DELETE FROM laps", "only a SELECT"),
            ("UPDATE laps SET lap_time_ms = 0", "only a SELECT"),
            ("INSERT INTO drivers (id) VALUES (1)", "only a SELECT"),
            ("DROP TABLE laps", "only a SELECT"),
            ("TRUNCATE laps", "only a SELECT"),
            ("COPY laps TO STDOUT", "only a SELECT"),
            ("SET statement_timeout = 0", "only a SELECT"),
            ("GRANT SELECT ON laps TO public", "only a SELECT"),
            ("COMMIT", "only a SELECT"),
            ("WITH gone AS (DELETE FROM laps RETURNING 1) SELECT 1", "only reading"),
            ("SELECT * INTO copy_of_laps FROM laps", "only reading"),
            ("SELECT * FROM laps FOR UPDATE", "only reading"),
            ("SELECT 1; SELECT 2", "exactly one"),
            ("SELECT 1; DELETE FROM laps", "exactly one"),
        ],
    )
    def test_anything_but_one_read_is_refused(self, sql: str, reason: str) -> None:
        with pytest.raises(SqlRejectedError, match=reason):
            validate_sql(sql)

    @pytest.mark.parametrize(
        ("sql", "table"),
        [
            ("SELECT * FROM ingestion_jobs", "ingestion_jobs"),
            ("SELECT * FROM reports", "reports"),
            ("SELECT * FROM sessions", "sessions"),
            ("SELECT * FROM pg_catalog.pg_roles", "pg_catalog.pg_roles"),
            ("SELECT * FROM information_schema.tables", "information_schema.tables"),
            ("SELECT * FROM public.laps", "public.laps"),
            ("SELECT * FROM laps JOIN pg_user ON true", "pg_user"),
        ],
    )
    def test_tables_outside_the_six_are_refused(self, sql: str, table: str) -> None:
        with pytest.raises(SqlRejectedError, match=table):
            validate_sql(sql)

    def test_a_cte_name_is_not_mistaken_for_a_table(self) -> None:
        validate_sql("WITH fast AS (SELECT * FROM laps) SELECT * FROM fast")

    def test_a_cte_cannot_launder_a_forbidden_table(self) -> None:
        with pytest.raises(SqlRejectedError, match="reports"):
            validate_sql("WITH r AS (SELECT * FROM reports) SELECT * FROM r")

    @pytest.mark.parametrize(
        "function",
        [
            "pg_sleep(10)",
            "pg_read_file('/etc/passwd')",
            "pg_terminate_backend(1)",
            "lo_create(0)",
            "dblink('host=x', 'select 1')",
            "set_config('statement_timeout', '0', false)",
            "nextval('laps_id_seq')",
            "query_to_xml('select 1', true, true, '')",
            "txid_current()",
            "loread(0, 100)",
            "lowrite(0, 'x')",
        ],
    )
    def test_functions_with_side_effects_are_refused(self, function: str) -> None:
        with pytest.raises(SqlRejectedError, match="not allowed"):
            validate_sql(f"SELECT {function}")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 'pg_authid'::regclass",
            "SELECT CAST('now' AS regproc)",
            "SELECT 'postgres'::regrole",
        ],
    )
    def test_casts_that_look_up_system_objects_are_refused(self, sql: str) -> None:
        with pytest.raises(SqlRejectedError, match="casting to reg"):
            validate_sql(sql)

    def test_ordinary_casts_are_fine(self) -> None:
        validate_sql("SELECT lap_time_ms::numeric / 1000, '1'::int FROM laps")

    def test_a_blocked_function_is_found_deep_in_the_query(self) -> None:
        with pytest.raises(SqlRejectedError, match="pg_sleep"):
            validate_sql(
                "SELECT * FROM laps WHERE lap_number IN "
                "(SELECT CASE WHEN pg_sleep(5) IS NULL THEN 1 END)"
            )

    @pytest.mark.parametrize("sql", ["SELEC 1", "SELECT FROM WHERE", ""])
    def test_unparseable_sql_is_refused_with_a_reason(self, sql: str) -> None:
        with pytest.raises(SqlRejectedError):
            validate_sql(sql)

    def test_every_forbidden_node_type_resolved_in_this_sqlglot(self) -> None:
        # Names are looked up defensively; a rename must not silently drop one.
        names = {node.__name__ for node in FORBIDDEN_NODES}
        assert {"Insert", "Update", "Delete", "Into", "Lock", "Copy", "Set", "Command"} <= names
