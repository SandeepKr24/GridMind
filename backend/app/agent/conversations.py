"""Conversations, held in memory and forgotten on restart.

An accepted v1 trade-off: nothing about a conversation is worth persisting,
and the frontend already treats an unknown conversation id (a 404) as a cue
to start afresh.

The store is bounded two ways so a public site cannot grow it without limit:
conversations idle past the TTL are dropped, and past `max_conversations` the
least recently used goes first. Each conversation keeps only its last few
turns, because only the most recent one is ever sent to the model.

It also remembers what a question waiting on ingestion resolved to. The
frontend asks the same question again once the fetch lands, and resolving it
a second time would spend an LLM call to learn what we already knew.
"""

from __future__ import annotations

import datetime as dt
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agent.entities import ResolvedEntities

#: Turns kept per conversation. Only the last is used; the rest are headroom.
MAX_TURNS = 6
#: Questions waiting on a fetch, per conversation.
MAX_PENDING = 4


@dataclass(frozen=True, slots=True)
class Turn:
    question: str
    answer: str
    #: None when the turn resolved nothing (a clarification, a refusal).
    entities: ResolvedEntities | None


@dataclass(slots=True)
class Conversation:
    id: str
    last_active: float
    turns: deque[Turn] = field(default_factory=lambda: deque(maxlen=MAX_TURNS))
    pending: OrderedDict[str, ResolvedEntities] = field(default_factory=OrderedDict)

    # No lock: two overlapping requests on one conversation (a double submit)
    # can both resolve and both append. Harmless beyond the duplicated work,
    # which per-IP rate limiting (step 19) bounds.

    def previous_entities(self) -> ResolvedEntities | None:
        """What the most recent turn that resolved anything was about."""
        return next((t.entities for t in reversed(self.turns) if t.entities), None)

    def record(self, turn: Turn) -> None:
        self.turns.append(turn)

    def remember_pending(self, question: str, entities: ResolvedEntities) -> None:
        self.pending[_key(question)] = entities
        self.pending.move_to_end(_key(question))
        while len(self.pending) > MAX_PENDING:
            self.pending.popitem(last=False)

    def take_pending(self, question: str) -> ResolvedEntities | None:
        return self.pending.pop(_key(question), None)


def _key(question: str) -> str:
    return " ".join(question.lower().split())


class ConversationStore:
    def __init__(
        self,
        *,
        ttl: dt.timedelta,
        max_conversations: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl.total_seconds()
        self._max = max_conversations
        self._clock = clock
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()

    def __len__(self) -> int:
        return len(self._conversations)

    def create(self) -> Conversation:
        self._evict_expired()
        conversation = Conversation(id=secrets.token_urlsafe(16), last_active=self._clock())
        self._conversations[conversation.id] = conversation
        while len(self._conversations) > self._max:
            self._conversations.popitem(last=False)
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        """The conversation, touched as active; None if unknown or expired."""
        self._evict_expired()
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return None
        conversation.last_active = self._clock()
        self._conversations.move_to_end(conversation_id)
        return conversation

    def _evict_expired(self) -> None:
        cutoff = self._clock() - self._ttl
        # Oldest first, so the scan stops at the first one still alive.
        while self._conversations:
            oldest = next(iter(self._conversations.values()))
            if oldest.last_active >= cutoff:
                break
            self._conversations.popitem(last=False)
