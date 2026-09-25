"""Settings are the boundary between the deployment and the application.

Everything here is about failing loudly at startup rather than quietly at 3am:
a missing credential, a pooled URL where a direct one is required, or a
read-only URL that is secretly the writer.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings

WRITER = "postgresql://neondb_owner:pw@ep-example-1234.c-3.aws.neon.tech/neondb"
READER = "postgresql://gridmind_readonly:pw2@ep-example-1234.c-3.aws.neon.tech/neondb"


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": WRITER,
        "database_url_readonly": READER,
    }
    values.update(overrides)
    # _env_file=None isolates the suite from the developer's real backend/.env.
    # Without it these tests pass or fail depending on whose machine they run on.
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestRequiredCredentials:
    def test_both_database_urls_are_required(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)  # type: ignore[call-arg]

        missing = {e["loc"][0] for e in exc.value.errors()}
        assert "database_url" in missing
        assert "database_url_readonly" in missing

    def test_blank_database_url_is_rejected(self) -> None:
        # An unfilled .env line reads as "" rather than absent, so emptiness
        # has to be rejected explicitly or it surfaces as a driver error later.
        with pytest.raises(ValidationError):
            make(database_url="")


class TestDriverNormalisation:
    def test_bare_postgresql_scheme_gets_the_psycopg_driver(self) -> None:
        # Neon hands out postgresql://. SQLAlchemy's async engine needs the
        # driver named, or it silently picks the sync psycopg2 dialect.
        assert make().database_url.startswith("postgresql+psycopg://")

    def test_postgres_alias_is_also_normalised(self) -> None:
        assert make(
            database_url=WRITER.replace("postgresql://", "postgres://")
        ).database_url.startswith("postgresql+psycopg://")

    def test_an_explicit_driver_is_left_alone(self) -> None:
        url = WRITER.replace("postgresql://", "postgresql+asyncpg://")
        assert make(database_url=url).database_url == url

    def test_normalisation_preserves_query_parameters(self) -> None:
        url = f"{WRITER}?sslmode=require&channel_binding=require"
        result = make(database_url=url).database_url
        assert result.endswith("?sslmode=require&channel_binding=require")


class TestNeonSpecificGuards:
    def test_pooled_host_is_rejected(self) -> None:
        # PgBouncer runs in transaction mode, which breaks psycopg's prepared
        # statements and any session-level SET. Catch it at startup, because at
        # runtime it surfaces as 'prepared statement "_pg3_0" already exists'.
        pooled = WRITER.replace("ep-example-1234.", "ep-example-1234-pooler.")
        with pytest.raises(ValidationError, match="pooler"):
            make(database_url=pooled)

    def test_pooled_host_is_rejected_for_the_readonly_url_too(self) -> None:
        pooled = READER.replace("ep-example-1234.", "ep-example-1234-pooler.")
        with pytest.raises(ValidationError, match="pooler"):
            make(database_url_readonly=pooled)

    def test_non_neon_hosts_are_unaffected(self) -> None:
        local = "postgresql://gridmind:pw@localhost:5432/gridmind"
        assert make(database_url=local, database_url_readonly=local.replace("gridmind:", "ro:"))


class TestReadOnlySeparation:
    def test_identical_urls_are_rejected(self) -> None:
        # The whole point of the second URL is that it is a different role. If
        # they match, the agent's SQL would run with write privileges and the
        # database-level safety net would be gone.
        with pytest.raises(ValidationError, match="same role"):
            make(database_url_readonly=WRITER)

    def test_same_user_on_a_different_host_is_still_rejected(self) -> None:
        other_host = WRITER.replace("ep-example-1234", "somewhere-else")
        with pytest.raises(ValidationError, match="same role"):
            make(database_url_readonly=other_host)

    def test_different_users_are_accepted(self) -> None:
        assert make().database_url_readonly.startswith("postgresql+psycopg://")


class TestCorsOrigins:
    def test_comma_separated_string_becomes_a_list(self) -> None:
        settings = make(cors_origins="http://localhost:3000, https://gridmind.app")
        assert settings.cors_origins == ["http://localhost:3000", "https://gridmind.app"]

    def test_blank_entries_are_dropped(self) -> None:
        assert make(cors_origins="http://a.test,,  ,http://b.test").cors_origins == [
            "http://a.test",
            "http://b.test",
        ]

    def test_empty_string_means_no_origins(self) -> None:
        assert make(cors_origins="").cors_origins == []

    def test_wildcard_is_rejected(self) -> None:
        # A public, unauthenticated API with '*' would let any page drive it.
        with pytest.raises(ValidationError, match="wildcard"):
            make(cors_origins="*")


class TestDefaults:
    def test_schema_defaults_to_gridmind(self) -> None:
        assert make().database_schema == "gridmind"

    def test_schema_must_be_a_plain_identifier(self) -> None:
        # It is interpolated into SET search_path, so it can never be free text.
        with pytest.raises(ValidationError):
            make(database_schema="gridmind; drop schema public cascade")

    def test_ingestion_concurrency_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            make(max_concurrent_ingestion_jobs=0)

    def test_groq_key_is_optional_so_the_api_can_boot_without_an_llm(self) -> None:
        # Race and report endpoints must work before an LLM key exists.
        assert make().groq_api_key is None

    def test_blank_groq_lines_count_as_unset(self) -> None:
        # `GROQ_MODEL=` in .env arrives as "", which must not look configured.
        settings = make(
            groq_api_key="  ", groq_model="", groq_fallback_model="", groq_reasoning_effort=""
        )

        assert settings.groq_api_key is None
        assert settings.groq_model is None
        assert settings.groq_fallback_model is None
        assert settings.groq_reasoning_effort is None

    def test_groq_key_is_hidden_from_repr(self) -> None:
        settings = make(groq_api_key="gsk_live_secret", groq_model=" openai/gpt-oss-20b ")

        assert "gsk_live_secret" not in repr(settings)
        assert settings.groq_api_key is not None
        assert settings.groq_api_key.get_secret_value() == "gsk_live_secret"
        assert settings.groq_model == "openai/gpt-oss-20b"

    def test_reasoning_effort_must_be_a_known_level(self) -> None:
        with pytest.raises(ValidationError):
            make(groq_reasoning_effort="maximum")
