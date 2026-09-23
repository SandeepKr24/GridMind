"""Engine configuration.

Everything checked here is invisible at runtime when it is wrong. A missing
`search_path` shows up as "relation does not exist" somewhere far away; a
missing `pool_pre_ping` shows up as one failed request after every Neon resume;
a writer that is accidentally read-only shows up only when ingestion first
tries to store a session.
"""

from __future__ import annotations

from app.config import Settings
from app.db.database import (
    IDLE_IN_TRANSACTION_TIMEOUT_MS,
    POOL_RECYCLE_SECONDS,
    Database,
    _pg_options,
    _server_settings,
    build_connect_args,
)

WRITER = "postgresql://neondb_owner:pw@ep-x.aws.neon.tech/neondb"
READER = "postgresql://gridmind_readonly:pw2@ep-x.aws.neon.tech/neondb"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": WRITER, "database_url_readonly": READER}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestServerSettings:
    def test_both_roles_are_pinned_to_the_configured_schema(self) -> None:
        settings = make_settings(database_schema="gridmind")
        assert _server_settings(settings, read_only=False)["search_path"] == "gridmind"
        assert _server_settings(settings, read_only=True)["search_path"] == "gridmind"

    def test_a_custom_schema_is_honoured(self) -> None:
        settings = make_settings(database_schema="analytics")
        assert _server_settings(settings, read_only=True)["search_path"] == "analytics"

    def test_reader_is_read_only_at_the_session_level(self) -> None:
        options = _server_settings(make_settings(), read_only=True)
        assert options["default_transaction_read_only"] == "on"

    def test_writer_is_not_read_only(self) -> None:
        # Guards against the copy-paste that would silently break ingestion.
        options = _server_settings(make_settings(), read_only=False)
        assert "default_transaction_read_only" not in options

    def test_both_roles_cap_idle_in_transaction(self) -> None:
        # An open transaction is the one thing that keeps a Neon compute awake,
        # so neither role may sit in one.
        expected = str(IDLE_IN_TRANSACTION_TIMEOUT_MS)
        assert (
            _server_settings(make_settings(), read_only=False)[
                "idle_in_transaction_session_timeout"
            ]
            == expected
        )
        assert (
            _server_settings(make_settings(), read_only=True)["idle_in_transaction_session_timeout"]
            == expected
        )


class TestPgOptions:
    def test_renders_libpq_option_flags(self) -> None:
        assert _pg_options({"search_path": "gridmind"}) == "-c search_path=gridmind"

    def test_joins_multiple_options_with_spaces(self) -> None:
        rendered = _pg_options({"search_path": "gridmind", "statement_timeout": "30000"})
        assert rendered == "-c search_path=gridmind -c statement_timeout=30000"

    def test_empty_options_render_empty(self) -> None:
        assert _pg_options({}) == ""


class TestEngines:
    def test_writer_and_reader_use_their_own_urls(self) -> None:
        db = Database(make_settings())
        assert db.writer.url.username == "neondb_owner"
        assert db.reader.url.username == "gridmind_readonly"

    def test_both_engines_use_the_async_psycopg_driver(self) -> None:
        # create_async_engine would fail loudly, but the wrong sync driver
        # would only surface under load.
        db = Database(make_settings())
        assert db.writer.url.drivername == "postgresql+psycopg"
        assert db.reader.url.drivername == "postgresql+psycopg"

    def test_pre_ping_is_enabled(self) -> None:
        # Neon closes idle connections at suspend. Without pre-ping the first
        # query after every resume fails.
        db = Database(make_settings())
        assert db.writer.pool._pre_ping is True
        assert db.reader.pool._pre_ping is True

    def test_connections_are_recycled_before_neon_suspends(self) -> None:
        # Suspend happens at 5 minutes; recycling must be shorter or we hand
        # out connections the server has already dropped.
        assert POOL_RECYCLE_SECONDS < 300
        db = Database(make_settings())
        assert db.writer.pool._recycle == POOL_RECYCLE_SECONDS

    def test_writer_connect_args_set_the_schema_and_stay_writable(self) -> None:
        options = build_connect_args(make_settings(), read_only=False)["options"]
        assert "-c search_path=gridmind" in options
        assert "default_transaction_read_only" not in options

    def test_reader_connect_args_carry_read_only(self) -> None:
        options = build_connect_args(make_settings(), read_only=True)["options"]
        assert "-c search_path=gridmind" in options
        assert "-c default_transaction_read_only=on" in options
