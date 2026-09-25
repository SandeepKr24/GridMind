"""The Groq client: request shape, parsing, retries and error mapping. No network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.llm import (
    JsonSchema,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    LLMUnavailableError,
    Message,
)
from app.llm.groq import MAX_INLINE_WAIT_SECONDS, GroqProvider, parse_completion

KEY = "gsk_test_secret"
MODEL = "openai/gpt-oss-20b"
QUESTION = [Message("system", "You are terse."), Message("user", "Who won?")]


def ok(content: str = "Verstappen.", **extra: Any) -> httpx.Response:
    payload = {
        "model": MODEL,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        **extra,
    }
    return httpx.Response(200, json=payload)


def error(
    status: int, message: str = "nope", code: str | None = None, **headers: str
) -> httpx.Response:
    body: dict[str, Any] = {"error": {"message": message, "type": "x"}}
    if code is not None:
        body["error"]["code"] = code
    return httpx.Response(status, json=body, headers=headers)


class Recorder:
    """Replays canned responses in order and records every request."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, index: int = 0) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[index].content)
        return body


def provider(recorder: Recorder, sleeps: list[float] | None = None, **kwargs: Any) -> GroqProvider:
    record = sleeps if sleeps is not None else []

    async def fake_sleep(seconds: float) -> None:
        record.append(seconds)

    return GroqProvider(
        KEY, MODEL, transport=httpx.MockTransport(recorder), sleep=fake_sleep, **kwargs
    )


class TestRequest:
    async def test_sends_messages_model_and_bearer_key(self) -> None:
        recorder = Recorder(ok())

        await provider(recorder).complete(QUESTION, max_tokens=64)

        request = recorder.requests[0]
        assert request.url == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        body = recorder.body()
        assert body["model"] == MODEL
        assert body["messages"] == [
            {"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Who won?"},
        ]
        assert body["max_completion_tokens"] == 64
        assert body["temperature"] == 0.0
        assert "response_format" not in body
        assert "reasoning_effort" not in body

    async def test_schema_becomes_a_json_schema_response_format(self) -> None:
        recorder = Recorder(ok('{"year": 2024}'))
        schema = JsonSchema("entities", {"type": "object"}, strict=True)

        await provider(recorder).complete(QUESTION, schema=schema)

        assert recorder.body()["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "entities", "strict": True, "schema": {"type": "object"}},
        }

    async def test_reasoning_effort_is_sent_only_when_configured(self) -> None:
        recorder = Recorder(ok())

        await provider(recorder, reasoning_effort="low").complete(QUESTION)

        assert recorder.body()["reasoning_effort"] == "low"

    def test_repr_never_contains_the_key(self) -> None:
        assert KEY not in repr(provider(Recorder()))

    def test_refuses_to_build_without_key_or_model(self) -> None:
        with pytest.raises(ValueError):
            GroqProvider("", MODEL)
        with pytest.raises(ValueError):
            GroqProvider(KEY, "")


class TestParsing:
    async def test_returns_text_model_and_usage(self) -> None:
        completion = await provider(Recorder(ok())).complete(QUESTION)

        assert completion.text == "Verstappen."
        assert completion.model == MODEL
        assert completion.usage.prompt_tokens == 42
        assert completion.usage.completion_tokens == 7
        assert completion.usage.total_tokens == 49
        assert completion.latency_ms >= 0

    async def test_json_parses_an_object(self) -> None:
        completion = await provider(Recorder(ok('{"year": 2024}'))).complete(QUESTION)

        assert completion.json() == {"year": 2024}

    @pytest.mark.parametrize("text", ["not json", "[1, 2]"])
    async def test_json_rejects_non_objects(self, text: str) -> None:
        completion = await provider(Recorder(ok(text))).complete(QUESTION)

        with pytest.raises(LLMInvalidResponseError):
            completion.json()

    def test_truncated_completion_is_rejected(self) -> None:
        payload = {"choices": [{"message": {"content": '{"ye'}, "finish_reason": "length"}]}

        with pytest.raises(LLMInvalidResponseError, match="cut off"):
            parse_completion(payload, fallback_model=MODEL, latency_ms=1)

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": "   "}}]},
        ],
    )
    def test_malformed_or_empty_payloads_are_rejected(self, payload: Any) -> None:
        with pytest.raises(LLMInvalidResponseError):
            parse_completion(payload, fallback_model=MODEL, latency_ms=1)

    def test_missing_usage_and_model_fall_back_to_defaults(self) -> None:
        payload = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}

        completion = parse_completion(payload, fallback_model=MODEL, latency_ms=5)

        assert completion.model == MODEL
        assert completion.usage.total_tokens == 0

    async def test_non_json_success_body_is_invalid(self) -> None:
        recorder = Recorder(httpx.Response(200, text="<html>"))

        with pytest.raises(LLMInvalidResponseError):
            await provider(recorder).complete(QUESTION)


class TestRateLimits:
    async def test_short_retry_after_is_waited_out(self) -> None:
        sleeps: list[float] = []
        recorder = Recorder(error(429, **{"retry-after": "2"}), ok())

        completion = await provider(recorder, sleeps).complete(QUESTION)

        assert completion.text == "Verstappen."
        assert sleeps == [2.0]

    async def test_per_minute_wait_above_a_few_seconds_is_still_waited_out(self) -> None:
        # An 8K token/min quota drained by a burst can ask for ~10s.
        sleeps: list[float] = []
        recorder = Recorder(error(429, **{"retry-after": "11.5"}), ok())

        await provider(recorder, sleeps).complete(QUESTION)

        assert sleeps == [11.5]

    async def test_long_retry_after_raises_immediately(self) -> None:
        # A per-day quota: waiting inside a chat request is pointless.
        recorder = Recorder(error(429, "tokens per day (TPD)", **{"retry-after": "3600"}))

        with pytest.raises(LLMRateLimitedError) as caught:
            await provider(recorder).complete(QUESTION)

        assert caught.value.retry_after == 3600.0
        assert "TPD" in str(caught.value)
        assert len(recorder.requests) == 1

    async def test_missing_retry_after_raises_immediately(self) -> None:
        recorder = Recorder(error(429))

        with pytest.raises(LLMRateLimitedError) as caught:
            await provider(recorder).complete(QUESTION)

        assert caught.value.retry_after is None

    async def test_persistent_short_rate_limit_eventually_raises(self) -> None:
        limited = {"retry-after": str(MAX_INLINE_WAIT_SECONDS)}
        recorder = Recorder(error(429, **limited), error(429, **limited), error(429, **limited))

        with pytest.raises(LLMRateLimitedError):
            await provider(recorder, retries=2).complete(QUESTION)

        assert len(recorder.requests) == 3

    def test_rate_limit_is_an_llm_error(self) -> None:
        # Callers that only care about "the model failed" can catch LLMError.
        assert issubclass(LLMRateLimitedError, LLMError)


class TestFailures:
    @pytest.mark.parametrize("status", [498, 500, 502, 503, 504])
    async def test_server_errors_are_retried_then_succeed(self, status: int) -> None:
        sleeps: list[float] = []
        recorder = Recorder(error(status), ok())

        await provider(recorder, sleeps).complete(QUESTION)

        assert sleeps == [1.0]

    async def test_server_error_retry_after_is_capped(self) -> None:
        sleeps: list[float] = []
        recorder = Recorder(error(503, **{"retry-after": "600"}), ok())

        await provider(recorder, sleeps).complete(QUESTION)

        assert sleeps == [MAX_INLINE_WAIT_SECONDS]

    async def test_network_errors_exhaust_retries_as_unavailable(self) -> None:
        sleeps: list[float] = []
        failure = httpx.ConnectError("down")
        recorder = Recorder(failure, failure, failure)

        with pytest.raises(LLMUnavailableError, match="ConnectError"):
            await provider(recorder, sleeps, retries=2).complete(QUESTION)

        assert sleeps == [1.0, 2.0]

    async def test_whole_call_is_bounded_by_the_deadline(self) -> None:
        async def slow(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return ok()

        groq = GroqProvider(KEY, MODEL, transport=httpx.MockTransport(slow), deadline_seconds=0.01)

        with pytest.raises(LLMUnavailableError, match="no answer within"):
            await groq.complete(QUESTION)

    async def test_bad_key_is_not_retried(self) -> None:
        recorder = Recorder(error(401, "Invalid API Key"))

        with pytest.raises(LLMError, match="API key") as caught:
            await provider(recorder).complete(QUESTION)

        assert type(caught.value) is LLMError
        assert KEY not in str(caught.value)
        assert len(recorder.requests) == 1

    async def test_schema_validation_failure_is_an_invalid_response(self) -> None:
        recorder = Recorder(error(400, "did not match schema", code="json_validate_failed"))

        with pytest.raises(LLMInvalidResponseError, match="schema"):
            await provider(recorder).complete(QUESTION)

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (error(404, "model not found"), "model not found"),
            (error(413, "request too large"), "request too large"),
            (httpx.Response(400, text="plain failure"), "plain failure"),
            (httpx.Response(400, text=""), "HTTP 400"),
        ],
    )
    async def test_other_client_errors_carry_the_provider_message(
        self, response: httpx.Response, expected: str
    ) -> None:
        with pytest.raises(LLMError, match=expected) as caught:
            await provider(Recorder(response)).complete(QUESTION)

        assert type(caught.value) is LLMError

    async def test_provider_error_text_is_bounded(self) -> None:
        recorder = Recorder(error(400, "x" * 5000))

        with pytest.raises(LLMError) as caught:
            await provider(recorder).complete(QUESTION)

        assert len(str(caught.value)) < 400
