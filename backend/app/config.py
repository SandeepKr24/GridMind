"""Application settings, loaded from the environment and validated at startup.

The validators here exist because every rule they enforce has a failure mode
that is hard to diagnose at runtime: a pooled Neon URL breaks prepared
statements deep inside the driver, and a read-only URL that is really the
writer removes the database-level safety net without any visible symptom.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Neon exposes the same database on two hostnames. The "-pooler" one routes
# through PgBouncer in transaction mode.
POOLER_HOST_MARKER = "-pooler."

_ASYNC_DRIVER = "postgresql+psycopg://"
_BARE_SCHEMES = ("postgresql://", "postgres://")
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _normalise_driver(url: str) -> str:
    """Name the async driver explicitly.

    Neon hands out `postgresql://`. SQLAlchemy maps that to psycopg2, which is
    synchronous, so `create_async_engine` would fail on a URL that looks
    perfectly correct.
    """
    for scheme in _BARE_SCHEMES:
        if url.startswith(scheme):
            return _ASYNC_DRIVER + url[len(scheme) :]
    return url


def _role_of(url: str) -> str | None:
    try:
        return urlsplit(url).username
    except ValueError:
        return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database -------------------------------------------------------
    database_url: str = Field(min_length=1)
    database_url_readonly: str = Field(min_length=1)
    database_schema: str = "gridmind"

    # --- LLM ------------------------------------------------------------
    # Optional: the data and report endpoints must boot without an LLM key.
    # SecretStr keeps the key out of reprs, tracebacks and logged settings.
    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    # Groq's quotas are per model, so a second model is a second budget.
    groq_fallback_model: str | None = None
    # Only for reasoning models (e.g. openai/gpt-oss-*). Reasoning tokens count
    # against the per-minute token quota, so "low" stretches the free tier.
    groq_reasoning_effort: Literal["low", "medium", "high"] | None = None
    groq_base_url: str = DEFAULT_GROQ_BASE_URL
    llm_timeout_seconds: float = Field(default=30.0, gt=0)

    # --- Ingestion ------------------------------------------------------
    fastf1_cache_dir: str = ".fastf1-cache"
    max_concurrent_ingestion_jobs: int = Field(default=2, gt=0)
    # Jobs running or waiting for a slot. Beyond this, new sessions get a 503.
    max_pending_ingestion_jobs: int = Field(default=8, gt=0)
    ingestion_job_timeout_seconds: int = Field(default=300, gt=0)
    max_sessions_per_question: int = Field(default=2, gt=0)
    # How long a season's calendar is held in memory before re-checking for
    # cancelled or moved rounds.
    schedule_cache_ttl_hours: int = Field(default=12, gt=0)

    # --- Standings ------------------------------------------------------
    jolpica_base_url: str = "https://api.jolpi.ca/ergast/f1"
    standings_cache_ttl_hours: int = Field(default=24, gt=0)

    # --- Conversations --------------------------------------------------
    conversation_ttl_minutes: int = Field(default=60, gt=0)
    max_conversations_in_memory: int = Field(default=500, gt=0)

    # --- Reports --------------------------------------------------------
    auto_report_enabled: bool = True
    # How often to look for a newly finished race. Checks outside a race's
    # window touch only the in-memory calendar, never the database.
    auto_report_check_hours: float = Field(default=3.0, gt=0)
    # Days after race day during which a missing report is still written.
    auto_report_window_days: int = Field(default=2, ge=0)

    # --- API ------------------------------------------------------------
    # NoDecode: without it pydantic-settings tries json.loads() on the raw env
    # value before any validator runs, so "http://localhost:3000" blows up as
    # invalid JSON. We want plain comma-separated values, parsed below.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Per client address. Each report costs several thousand tokens, so its
    # budget is the tightest.
    rate_limit_chat_per_minute: int = Field(default=10, gt=0)
    rate_limit_ingest_per_hour: int = Field(default=20, gt=0)
    rate_limit_report_per_hour: int = Field(default=5, gt=0)

    @field_validator("database_url", "database_url_readonly")
    @classmethod
    def _reject_pooled_and_name_the_driver(cls, value: str) -> str:
        host = urlsplit(value).hostname or ""
        if POOLER_HOST_MARKER in host:
            raise ValueError(
                "refusing a '-pooler' host: Neon's pooler runs PgBouncer in transaction "
                "mode, which breaks prepared statements and session-level SET. Use the "
                "direct endpoint (DATABASE_URL_UNPOOLED in .env.local)."
            )
        return _normalise_driver(value)

    @field_validator(
        "groq_api_key", "groq_model", "groq_fallback_model", "groq_reasoning_effort", mode="before"
    )
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        # An unfilled `GROQ_MODEL=` line in .env arrives as "", not as absent.
        # Left alone, "" would count as configured and fail on the first call.
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("database_schema")
    @classmethod
    def _schema_must_be_an_identifier(cls, value: str) -> str:
        # Interpolated into `SET search_path`, which takes no bind parameters.
        if not _IDENTIFIER.match(value):
            raise ValueError(f"database_schema must be a plain lowercase identifier, got {value!r}")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError(
                "wildcard CORS origin is not allowed: this API is public and "
                "unauthenticated, so any page could drive it. List origins explicitly."
            )
        return value

    @model_validator(mode="after")
    def _readonly_must_be_a_different_role(self) -> Settings:
        writer, reader = _role_of(self.database_url), _role_of(self.database_url_readonly)
        if writer is not None and writer == reader:
            raise ValueError(
                f"database_url_readonly uses the same role as database_url ({writer!r}). "
                "The agent's SQL would then run with write privileges, and the "
                "database-level safety net would be gone."
            )
        return self
