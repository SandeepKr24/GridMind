"""Groq, through its OpenAI-compatible chat completions endpoint.

Plain httpx rather than the Groq SDK: it is one endpoint, and owning the
request means owning the retry policy, which is the part that matters on a
free tier (30 requests/min, 8K tokens/min, 200K tokens/day per model at the
time of writing).

Retry policy:
- network errors and 5xx: bounded retries with backoff, then Unavailable;
- 429 with a short `retry-after`: wait it out once or twice, since a
  per-minute window clears within seconds (a burst against an 8K token/min
  quota can still ask for ten or more);
- 429 with a long or missing `retry-after`: raise RateLimited at once. That is
  a per-day quota, and holding a chat request open for hours helps nobody.

The whole sequence also runs under one deadline, so retries cannot stretch a
single call to several times the per-attempt timeout.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import DEFAULT_GROQ_BASE_URL
from app.llm.base import (
    Completion,
    JsonSchema,
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    LLMUnavailableError,
    Message,
    ReasoningEffort,
    Usage,
)
from app.llm.text import plain_text

logger = logging.getLogger(__name__)

#: A 429 asking for longer than this is not a per-minute window.
MAX_INLINE_WAIT_SECONDS = 15.0
#: Upper bound on one complete() call, retries and waits included.
DEFAULT_DEADLINE_SECONDS = 60.0
#: 498 is Groq's "capacity exceeded"; it behaves like a 503.
RETRYABLE = frozenset({498, 500, 502, 503, 504})
#: Provider error text is echoed into our logs and errors; keep it bounded.
MAX_ERROR_TEXT = 200


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        return None


def _error_text(response: httpx.Response) -> str:
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text
    return str(message)[:MAX_ERROR_TEXT] or f"HTTP {response.status_code}"


def _error_code(response: httpx.Response) -> str | None:
    try:
        code = response.json()["error"].get("code")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return str(code) if code is not None else None


def _is_generation_failure(response: httpx.Response) -> bool:
    """A 400 about what the model wrote, not about our request.

    Groq reports these two ways: `json_validate_failed` when the output misses
    the schema, and "Parsing failed" when it cannot be parsed at all. Both carry
    a `failed_generation` field, which a genuinely bad request does not.
    """
    if _error_code(response) == "json_validate_failed":
        return True
    try:
        return "failed_generation" in response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return False


def _failed_generation(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"].get("failed_generation") or "")
    except (ValueError, KeyError, TypeError, AttributeError):
        return ""


def parse_completion(payload: Any, *, fallback_model: str, latency_ms: int) -> Completion:
    try:
        choice = payload["choices"][0]
        content = choice["message"].get("content")
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise LLMInvalidResponseError(f"unexpected completion payload: {error!r}") from error

    if finish_reason == "length":
        # A truncated JSON object is unparseable, and a truncated answer is
        # misleading. Either way the caller has to know.
        raise LLMInvalidResponseError("completion was cut off at max_tokens")
    if not isinstance(content, str) or not content.strip():
        raise LLMInvalidResponseError("completion has no content")

    usage = payload.get("usage") or {}
    return Completion(
        # The model's typographic spaces and hyphens, made plain (llm/text.py).
        text=plain_text(content),
        model=str(payload.get("model") or fallback_model),
        usage=Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        ),
        latency_ms=latency_ms,
    )


class GroqProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_GROQ_BASE_URL,
        reasoning_effort: str | None = None,
        timeout_seconds: float = 30.0,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or not model:
            raise ValueError("GroqProvider needs both an API key and a model")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout_seconds
        self._deadline = deadline_seconds
        self._retries = retries
        self._transport = transport
        self._sleep = sleep

    def __repr__(self) -> str:
        # Never the key.
        return f"GroqProvider(model={self._model!r})"

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
        reasoning_effort: ReasoningEffort | None = None,
    ) -> Completion:
        body = self._body(
            messages, schema, max_tokens, temperature, reasoning_effort or self._reasoning_effort
        )
        started = time.monotonic()
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as http:
            try:
                async with asyncio.timeout(self._deadline):
                    payload = await self._post(http, body)
            except TimeoutError as error:
                raise LLMUnavailableError(
                    f"groq {self._model}: no answer within {self._deadline:.0f}s"
                ) from error
        latency_ms = round((time.monotonic() - started) * 1000)

        completion = parse_completion(payload, fallback_model=self._model, latency_ms=latency_ms)
        logger.info(
            "llm model=%s latency_ms=%d prompt_tokens=%d completion_tokens=%d",
            completion.model,
            completion.latency_ms,
            completion.usage.prompt_tokens,
            completion.usage.completion_tokens,
        )
        return completion

    def _body(
        self,
        messages: list[Message],
        schema: JsonSchema | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.name,
                    "strict": schema.strict,
                    "schema": schema.schema,
                },
            }
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        return body

    async def _post(self, http: httpx.AsyncClient, body: dict[str, Any]) -> Any:
        failure = "no attempt made"
        for attempt in range(self._retries + 1):
            has_retries_left = attempt < self._retries
            try:
                response = await http.post("/chat/completions", json=body)
            except httpx.HTTPError as error:
                failure = type(error).__name__
                delay = 2.0**attempt
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as error:
                        raise LLMInvalidResponseError("response was not JSON") from error
                self._raise_unless_retryable(response, has_retries_left)
                failure = f"HTTP {response.status_code}"
                wait = _retry_after(response)
                # A 5xx may also send retry-after; never hold a request for long.
                delay = min(wait, MAX_INLINE_WAIT_SECONDS) if wait is not None else 2.0**attempt

            if has_retries_left:
                logger.warning("groq %s: %s; retrying in %.1fs", self._model, failure, delay)
                await self._sleep(delay)
        raise LLMUnavailableError(f"groq {self._model}: {failure} after {self._retries + 1} tries")

    def _raise_unless_retryable(self, response: httpx.Response, has_retries_left: bool) -> None:
        status = response.status_code
        if status == 429:
            wait = _retry_after(response)
            if has_retries_left and wait is not None and wait <= MAX_INLINE_WAIT_SECONDS:
                return
            raise LLMRateLimitedError(
                f"groq {self._model} rate limited: {_error_text(response)}", retry_after=wait
            )
        if status in RETRYABLE:
            return
        if status == 400 and _is_generation_failure(response):
            # What the model actually produced; the only way to fix a prompt.
            logger.warning(
                "groq %s output rejected; generation began: %.300r",
                self._model,
                _failed_generation(response),
            )
            raise LLMInvalidResponseError(
                f"groq {self._model} output was unusable: {_error_text(response)}"
            )
        if status == 401:
            raise LLMError("groq rejected the API key")
        raise LLMError(f"groq {self._model} HTTP {status}: {_error_text(response)}")
