"""Try a second model when the first is rate limited or down.

On Groq, quotas are per model, so a second model is a second free-tier
budget. Only quota and availability failures fall through: a bad request or
an unusable answer would fail the same way on the fallback, and trying it
would just spend that budget too.
"""

from __future__ import annotations

import logging

from app.llm.base import (
    Completion,
    JsonSchema,
    LLMProvider,
    LLMRateLimitedError,
    LLMUnavailableError,
    Message,
)

logger = logging.getLogger(__name__)


class FallbackProvider:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def __repr__(self) -> str:
        return f"FallbackProvider({self._primary!r}, {self._fallback!r})"

    @property
    def model(self) -> str:
        return self._primary.model

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion:
        try:
            return await self._primary.complete(
                messages, schema=schema, max_tokens=max_tokens, temperature=temperature
            )
        except (LLMRateLimitedError, LLMUnavailableError) as error:
            logger.warning(
                "llm %s failed (%s); falling back to %s",
                self._primary.model,
                type(error).__name__,
                self._fallback.model,
            )
        return await self._fallback.complete(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature
        )
