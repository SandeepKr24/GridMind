"""Fallback between models, and building the provider from settings."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.llm import (
    Completion,
    FallbackProvider,
    GroqProvider,
    JsonSchema,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    LLMUnavailableError,
    Message,
    build_llm,
)

QUESTION = [Message("user", "Who won?")]
WRITER = "postgresql://neondb_owner:pw@ep-example-1234.c-3.aws.neon.tech/neondb"
READER = "postgresql://gridmind_readonly:pw2@ep-example-1234.c-3.aws.neon.tech/neondb"


class FakeProvider:
    def __init__(self, model: str, outcome: str | Exception) -> None:
        self._model = model
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion:
        self.calls.append({"schema": schema, "max_tokens": max_tokens, "temperature": temperature})
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return Completion(text=self._outcome, model=self._model)


class TestFallbackProvider:
    async def test_primary_answer_is_used_without_touching_fallback(self) -> None:
        primary, fallback = FakeProvider("a", "from a"), FakeProvider("b", "from b")

        completion = await FallbackProvider(primary, fallback).complete(QUESTION)

        assert completion.model == "a"
        assert fallback.calls == []

    @pytest.mark.parametrize(
        "failure", [LLMRateLimitedError("quota", retry_after=60), LLMUnavailableError("down")]
    )
    async def test_quota_or_outage_falls_through_with_the_same_arguments(
        self, failure: LLMError
    ) -> None:
        primary, fallback = FakeProvider("a", failure), FakeProvider("b", "from b")
        schema = JsonSchema("x", {"type": "object"})

        completion = await FallbackProvider(primary, fallback).complete(
            QUESTION, schema=schema, max_tokens=99, temperature=0.3
        )

        assert completion.model == "b"
        assert fallback.calls == [{"schema": schema, "max_tokens": 99, "temperature": 0.3}]

    @pytest.mark.parametrize("failure", [LLMError("bad request"), LLMInvalidResponseError("junk")])
    async def test_request_and_answer_problems_do_not_fall_through(self, failure: LLMError) -> None:
        primary, fallback = FakeProvider("a", failure), FakeProvider("b", "from b")

        with pytest.raises(type(failure)):
            await FallbackProvider(primary, fallback).complete(QUESTION)

        assert fallback.calls == []

    async def test_fallback_failure_propagates(self) -> None:
        primary = FakeProvider("a", LLMUnavailableError("down"))
        fallback = FakeProvider("b", LLMRateLimitedError("quota"))

        with pytest.raises(LLMRateLimitedError):
            await FallbackProvider(primary, fallback).complete(QUESTION)

    def test_reports_the_primary_model(self) -> None:
        provider = FallbackProvider(FakeProvider("a", "x"), FakeProvider("b", "y"))

        assert provider.model == "a"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"database_url": WRITER, "database_url_readonly": READER}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


class TestBuildLlm:
    def test_no_key_means_no_llm(self) -> None:
        assert build_llm(settings(groq_model="m")) is None

    def test_no_model_means_no_llm(self) -> None:
        assert build_llm(settings(groq_api_key="k")) is None

    def test_key_and_model_build_a_groq_provider(self) -> None:
        llm = build_llm(settings(groq_api_key="k", groq_model="m"))

        assert isinstance(llm, GroqProvider)
        assert llm.model == "m"

    def test_fallback_model_wraps_two_providers(self) -> None:
        llm = build_llm(settings(groq_api_key="k", groq_model="m", groq_fallback_model="f"))

        assert isinstance(llm, FallbackProvider)
        assert llm.model == "m"
        assert "'f'" in repr(llm)

    def test_fallback_identical_to_primary_is_ignored(self) -> None:
        llm = build_llm(settings(groq_api_key="k", groq_model="m", groq_fallback_model="m"))

        assert isinstance(llm, GroqProvider)
