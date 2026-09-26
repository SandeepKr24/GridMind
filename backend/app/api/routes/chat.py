"""POST /api/chat: one question, one reply.

Everything the user should read comes back as a 200 with an `answer`:
clarifying questions, refusals, "the data cannot answer that". HTTP errors are
kept for what the frontend handles specially (`frontend/lib/api/client.ts`):

- 404 for a conversation the server has forgotten; the page retries once as a
  new conversation;
- 429 with Retry-After when the LLM's free tier is exhausted, or this client
  has asked too often (`app/api/rate_limit.py`);
- 503 with Retry-After when something upstream is down or busy, or chat is
  not configured on this server.

The whole question runs under one deadline, below the frontend's 30 second
request timeout, so the user sees "try again" rather than a hung request.
"""

from __future__ import annotations

import asyncio
import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.entity_resolver import CalendarUnavailableError
from app.api.rate_limit import rate_limit
from app.api.schemas.chat import ChatRequest, ChatResponse
from app.ingestion.runner import IngestBusyError
from app.llm import LLMError, LLMRateLimitedError, LLMUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

#: The frontend gives up at 30 seconds.
CHAT_DEADLINE_SECONDS = 25.0
RETRY_AFTER_SECONDS = 30
#: Used when the provider rate-limits without saying for how long.
DEFAULT_RATE_LIMIT_WAIT = 60


def _unavailable(detail: str, retry_after: int = RETRY_AFTER_SECONDS) -> HTTPException:
    return HTTPException(503, detail=detail, headers={"Retry-After": str(retry_after)})


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit("chat"))])
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    agent = request.app.state.chat
    if agent is None:
        raise _unavailable("Chat is not configured on this server.", retry_after=3600)

    store = request.app.state.conversations
    if body.conversation_id is None:
        conversation = store.create()
    else:
        conversation = store.get(body.conversation_id)
        if conversation is None:
            raise HTTPException(404, detail="Unknown conversation")

    try:
        async with asyncio.timeout(CHAT_DEADLINE_SECONDS):
            reply = await agent.ask(body.message, conversation)
    except LLMRateLimitedError as error:
        wait = math.ceil(error.retry_after or DEFAULT_RATE_LIMIT_WAIT)
        raise HTTPException(
            429,
            detail="The AI model is at its usage limit. Try again shortly.",
            headers={"Retry-After": str(wait)},
        ) from error
    except TimeoutError as error:
        logger.warning("chat question ran past %.0fs", CHAT_DEADLINE_SECONDS)
        raise _unavailable("That took too long to answer. Try again in a moment.") from error
    except IngestBusyError as error:
        raise _unavailable(
            "The server is busy fetching other races. Try again in a minute.", 60
        ) from error
    except CalendarUnavailableError as error:
        raise _unavailable("The race calendar could not be loaded. Try again shortly.") from error
    except LLMUnavailableError as error:
        raise _unavailable("The AI model is unavailable right now. Try again shortly.") from error
    except LLMError as error:
        logger.exception("chat: the model failed")
        raise _unavailable("The AI model could not answer that. Try asking again.") from error
    except Exception as error:
        # Anything else is our bug. Log it in full; show nothing of it.
        logger.exception("chat: unexpected failure")
        raise _unavailable("Something went wrong answering that. Try again.") from error
    return ChatResponse.from_reply(reply, conversation.id)
