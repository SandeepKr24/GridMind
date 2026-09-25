"""SQL generation: what the model is told, and what is accepted back. No network."""

from __future__ import annotations

import datetime as dt

import pytest

from app.agent.entities import ResolvedSession
from app.agent.session_context import NamedId, SessionContext, StoredSession
from app.agent.sql_generator import (
    ROW_LIMIT,
    SCHEMA,
    SYSTEM_PROMPT,
    QueryType,
    build_messages,
    describe_context,
    generate_sql,
    parse_output,
)
from app.db.models.enums import SessionType
from app.llm import Completion, JsonSchema, LLMInvalidResponseError, Message

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
CONTEXT = SessionContext(
    sessions=(StoredSession(57, SPA, ()),),
    drivers=(NamedId("Norris", 4, "Lando Norris (NOR)"),),
    constructors=(NamedId("Ferrari", 12, "Ferrari"),),
)


class FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[list[Message], JsonSchema | None, int]] = []

    @property
    def model(self) -> str:
        return "fake"

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion:
        self.calls.append((messages, schema, max_tokens))
        return Completion(text=self.text, model="fake")


class TestPrompt:
    def test_context_lists_session_driver_and_team_ids(self) -> None:
        assert describe_context(CONTEXT) == (
            "Sessions:\n"
            "- session_id 57: 2024 Belgian Grand Prix race\n"
            "Drivers named: Lando Norris (NOR) = driver_id 4\n"
            "Teams named: Ferrari = constructor_id 12"
        )

    def test_context_without_names_lists_only_sessions(self) -> None:
        bare = SessionContext(sessions=CONTEXT.sessions)

        assert describe_context(bare) == "Sessions:\n- session_id 57: 2024 Belgian Grand Prix race"

    def test_question_follows_the_context(self) -> None:
        system, user = build_messages("  Who won?  ", CONTEXT)

        assert system.role == "system"
        assert user.content.endswith("\nQuestion: Who won?")

    def test_a_previous_failure_is_passed_back_for_a_correction(self) -> None:
        _, user = build_messages("Who won?", CONTEXT, previous_error='column "x" does not exist')

        assert user.content.endswith(
            'Your previous query failed: column "x" does not exist\nWrite a corrected query.'
        )

    @pytest.mark.parametrize(
        "rule",
        [
            "track_status = '1'",  # safety-car laps are not race pace
            "not the stationary time",  # pit lane transit, not the stop
            "Never look sessions up by name",
            f"LIMIT {ROW_LIMIT}",
            "set sql to null",
            "in its own CTE before",  # laps x pit_stops fan-out, seen live
            "counting laps (e.g. laps led",  # pace filters undercounted laps led
        ],
    )
    def test_prompt_carries_the_rules_live_runs_needed(self, rule: str) -> None:
        assert rule in SYSTEM_PROMPT

    def test_schema_is_closed_and_strict(self) -> None:
        assert SCHEMA.strict
        assert SCHEMA.schema["additionalProperties"] is False
        assert SCHEMA.schema["required"] == ["query_type", "sql", "cannot_answer"]
        assert SCHEMA.schema["properties"]["query_type"]["enum"] == [q.value for q in QueryType]


class TestParsing:
    def test_a_query_is_accepted_without_its_trailing_semicolon(self) -> None:
        query = parse_output(
            {"query_type": "result", "sql": " SELECT 1; ", "cannot_answer": "ignored"}
        )

        assert query.sql == "SELECT 1"
        assert query.query_type is QueryType.RESULT
        # A reason only counts when there is no query.
        assert query.cannot_answer is None

    def test_a_reason_instead_of_a_query(self) -> None:
        query = parse_output(
            {"query_type": "other", "sql": None, "cannot_answer": "Weather is not stored."}
        )

        assert query.sql is None
        assert query.cannot_answer == "Weather is not stored."

    @pytest.mark.parametrize(
        "payload",
        [
            {"query_type": "other", "sql": None, "cannot_answer": None},
            {"query_type": "other", "sql": "  ", "cannot_answer": " "},
            {"query_type": "gossip", "sql": "SELECT 1", "cannot_answer": None},
        ],
    )
    def test_output_with_nothing_usable_is_rejected(self, payload: dict[str, object]) -> None:
        with pytest.raises(LLMInvalidResponseError):
            parse_output(payload)

    async def test_generate_sends_the_schema_and_a_reasoning_budget(self) -> None:
        llm = FakeLLM('{"query_type": "pace", "sql": "SELECT 1", "cannot_answer": null}')

        query = await generate_sql(llm, "Norris pace?", CONTEXT)

        assert query.query_type is QueryType.PACE
        _, schema, max_tokens = llm.calls[0]
        assert schema is SCHEMA
        assert max_tokens >= 1024
