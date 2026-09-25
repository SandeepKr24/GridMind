"""LLM access for the agent. Everything outside this package uses `LLMProvider`."""

from __future__ import annotations

import logging

from app.config import Settings
from app.llm.base import (
    Completion,
    JsonSchema,
    LLMError,
    LLMInvalidResponseError,
    LLMProvider,
    LLMRateLimitedError,
    LLMUnavailableError,
    Message,
    Usage,
)
from app.llm.fallback import FallbackProvider
from app.llm.groq import GroqProvider

logger = logging.getLogger(__name__)

__all__ = [
    "Completion",
    "FallbackProvider",
    "GroqProvider",
    "JsonSchema",
    "LLMError",
    "LLMInvalidResponseError",
    "LLMProvider",
    "LLMRateLimitedError",
    "LLMUnavailableError",
    "Message",
    "Usage",
    "build_llm",
]


def build_llm(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None when no LLM is configured.

    None is a normal state, not an error: the race, standings and ingestion
    endpoints work without an LLM, and only chat needs one.
    """
    if settings.groq_api_key is None or settings.groq_model is None:
        logger.warning("no GROQ_API_KEY/GROQ_MODEL configured; chat is disabled")
        return None

    api_key = settings.groq_api_key.get_secret_value()

    def groq(model: str) -> GroqProvider:
        return GroqProvider(
            api_key,
            model,
            base_url=settings.groq_base_url,
            reasoning_effort=settings.groq_reasoning_effort,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    primary = groq(settings.groq_model)
    fallback_model = settings.groq_fallback_model
    if fallback_model is None or fallback_model == settings.groq_model:
        return primary
    return FallbackProvider(primary, groq(fallback_model))
