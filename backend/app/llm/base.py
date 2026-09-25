"""The provider-neutral LLM interface.

The agent talks to `LLMProvider` and never to Groq directly, so the model and
even the vendor can change through configuration. The error types are the
contract that matters most: a rate limit on a free tier is an ordinary,
expected event, and the API has to tell it apart from an outage or a bad
answer to respond with "try again shortly" rather than a generic 500.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """The model could not produce a usable completion. Not worth retrying."""


class LLMRateLimitedError(LLMError):
    """The provider refused the request for quota reasons.

    `retry_after` is in seconds when the provider said; a per-day quota can
    make it hours, so callers must not blindly sleep on it.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMUnavailableError(LLMError):
    """The provider failed or could not be reached. Transient, probably."""


class LLMInvalidResponseError(LLMError):
    """The provider answered, but not with something we can use."""


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class JsonSchema:
    """Constrain the completion to one JSON object matching `schema`.

    With `strict`, the provider guarantees conformance, but requires every
    property to be listed in `required` and `additionalProperties: false` on
    every object. Without it, conformance is best effort.
    """

    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    #: The model that actually answered, which differs from the configured
    #: one when a fallback served the request.
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0

    def json(self) -> dict[str, Any]:
        """The completion parsed as a JSON object."""
        try:
            value = json.loads(self.text)
        except ValueError as error:
            raise LLMInvalidResponseError(f"completion is not valid JSON: {error}") from error
        if not isinstance(value, dict):
            raise LLMInvalidResponseError("completion is JSON but not an object")
        return value


class LLMProvider(Protocol):
    @property
    def model(self) -> str: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion: ...
