"""The in-memory conversation store: bounded, expiring, and follow-up aware."""

from __future__ import annotations

import datetime as dt

from app.agent.conversations import (
    MAX_PENDING,
    MAX_TURNS,
    ConversationStore,
    ResolvedQuestion,
    Turn,
)
from app.agent.entities import Intent, ResolvedEntities

SPA = ResolvedEntities(Intent.SESSION, drivers=("Norris",))
STANDINGS = ResolvedEntities(Intent.STANDINGS, year=2024)
AT_SPA = ResolvedQuestion("Who won at Spa 2024?", SPA)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def store(clock: Clock, *, ttl_minutes: int = 60, max_conversations: int = 3) -> ConversationStore:
    return ConversationStore(
        ttl=dt.timedelta(minutes=ttl_minutes), max_conversations=max_conversations, clock=clock
    )


class TestLifetime:
    def test_a_created_conversation_can_be_found_again(self) -> None:
        conversations = store(Clock())
        created = conversations.create()

        assert conversations.get(created.id) is created

    def test_ids_are_unguessable_and_distinct(self) -> None:
        conversations = store(Clock(), max_conversations=100)
        ids = {conversations.create().id for _ in range(50)}

        assert len(ids) == 50
        assert all(len(i) >= 20 for i in ids)

    def test_an_unknown_id_is_none(self) -> None:
        assert store(Clock()).get("nope") is None

    def test_an_idle_conversation_expires(self) -> None:
        clock = Clock()
        conversations = store(clock, ttl_minutes=60)
        created = conversations.create()

        clock.now += 61 * 60

        assert conversations.get(created.id) is None
        assert len(conversations) == 0

    def test_activity_keeps_a_conversation_alive(self) -> None:
        clock = Clock()
        conversations = store(clock, ttl_minutes=60)
        created = conversations.create()

        clock.now += 50 * 60
        conversations.get(created.id)
        clock.now += 50 * 60

        assert conversations.get(created.id) is created

    def test_past_the_cap_the_least_recently_used_goes(self) -> None:
        clock = Clock()
        conversations = store(clock, max_conversations=2)
        first, second = conversations.create(), conversations.create()
        conversations.get(first.id)  # first is now the most recent

        conversations.create()

        assert conversations.get(second.id) is None
        assert conversations.get(first.id) is first
        assert len(conversations) == 2


class TestTurns:
    def test_the_previous_entities_skip_turns_that_resolved_nothing(self) -> None:
        conversation = store(Clock()).create()
        conversation.record(Turn("Who won at Spa 2024?", "Hamilton", SPA))
        conversation.record(Turn("Which year?", "Which year?", None))

        assert conversation.previous_entities() is SPA

    def test_a_new_conversation_has_nothing_previous(self) -> None:
        conversation = store(Clock()).create()

        assert conversation.previous_entities() is None
        assert conversation.last_turn() is None

    def test_the_last_turn_includes_a_clarification(self) -> None:
        conversation = store(Clock()).create()
        conversation.record(Turn("Who won at Spa 2024?", "Hamilton", SPA))
        asked_back = Turn("Who won at Monza?", "Which year's Monza do you mean?", None, True)
        conversation.record(asked_back)

        assert conversation.last_turn() is asked_back

    def test_only_the_last_turns_are_kept(self) -> None:
        conversation = store(Clock()).create()
        for i in range(MAX_TURNS + 3):
            conversation.record(Turn(f"q{i}", "a", STANDINGS))

        assert len(conversation.turns) == MAX_TURNS
        assert conversation.turns[0].question == "q3"


class TestPending:
    def test_a_pending_question_is_found_despite_spacing_and_case(self) -> None:
        conversation = store(Clock()).create()
        conversation.remember_pending("Who won at  Spa 2024?", AT_SPA)

        assert conversation.take_pending("who won at spa 2024?") is AT_SPA
        # Taken once: a second ask resolves afresh.
        assert conversation.take_pending("who won at spa 2024?") is None

    def test_pending_questions_are_bounded(self) -> None:
        conversation = store(Clock()).create()
        for i in range(MAX_PENDING + 2):
            conversation.remember_pending(f"q{i}", AT_SPA)

        assert len(conversation.pending) == MAX_PENDING
        assert conversation.take_pending("q0") is None
        assert conversation.take_pending(f"q{MAX_PENDING + 1}") is AT_SPA
