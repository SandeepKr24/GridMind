"""The SQL agent: one pass when all goes well, bounded recovery when not. No network."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence

import pytest

from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.executor import QueryFailedError, QueryResult
from app.agent.session_context import StoredSession
from app.agent.sql_agent import UNFINISHED_ANSWER, SqlAgent, SqlStatus
from app.agent.sql_generator import QueryType
from app.db.models.enums import SessionType
from app.llm import (
    Completion,
    JsonSchema,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    Message,
)
from tests.test_session_context import GRID

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
ROWS = QueryResult(("full_name",), (("Lewis Hamilton",),), truncated=False, elapsed_ms=3)
EMPTY = QueryResult(("full_name",), (), truncated=False, elapsed_ms=2)


def query(sql: str | None, reason: str | None = None, kind: str = "result") -> str:
    return json.dumps({"query_type": kind, "sql": sql, "cannot_answer": reason})


class ScriptedLLM:
    """Replies in order; an exception in the script is raised instead."""

    def __init__(self, *script: str | Exception) -> None:
        self._script = list(script)
        self.prompts: list[str] = []

    @property
    def model(self) -> str:
        return "scripted"

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion:
        self.prompts.append(messages[-1].content)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return Completion(text=step, model="scripted")


class Directory:
    async def load(self, sessions: Sequence[ResolvedSession]) -> tuple[StoredSession, ...]:
        return tuple(StoredSession(57, s, GRID) for s in sessions)


class Runner:
    """Fails with the given errors in order, then returns `result`."""

    def __init__(self, *errors: str, result: QueryResult = ROWS) -> None:
        self._errors = list(errors)
        self._result = result
        self.ran: list[str] = []

    async def run(self, sql: str) -> QueryResult:
        self.ran.append(sql)
        if self._errors:
            raise QueryFailedError(self._errors.pop(0))
        return self._result


def entities(*drivers: str) -> ResolvedEntities:
    return ResolvedEntities(Intent.SESSION, sessions=(SPA,), drivers=drivers)


def agent(llm: ScriptedLLM, runner: Runner | None = None) -> SqlAgent:
    return SqlAgent(llm, Directory(), runner or Runner())


class TestFirstTime:
    async def test_rows_come_back_with_the_query_and_its_type(self) -> None:
        runner = Runner()

        outcome = await agent(ScriptedLLM(query("SELECT 1")), runner).answer("Who won?", entities())

        assert outcome.status is SqlStatus.ANSWERED
        assert outcome.query_type is QueryType.RESULT
        assert outcome.sql == "SELECT 1"
        assert outcome.result == ROWS
        assert outcome.attempts == 1
        assert runner.ran == ["SELECT 1"]

    async def test_an_empty_result_is_an_answer_and_is_not_retried(self) -> None:
        llm = ScriptedLLM(query("SELECT 1 WHERE false"))

        outcome = await agent(llm, Runner(result=EMPTY)).answer("Penalties?", entities())

        assert outcome.status is SqlStatus.ANSWERED
        assert outcome.result is not None and outcome.result.is_empty
        assert len(llm.prompts) == 1

    async def test_drivers_named_reach_the_prompt_as_ids(self) -> None:
        llm = ScriptedLLM(query("SELECT 1"))

        await agent(llm).answer("Norris pace?", entities("Norris"))

        assert "Lando Norris (NOR) = driver_id 4" in llm.prompts[0]


class TestNoSqlSpent:
    async def test_an_unknown_driver_is_asked_about_before_any_llm_call(self) -> None:
        llm = ScriptedLLM()

        outcome = await agent(llm).answer("?", entities("Schumacher"))

        assert outcome.status is SqlStatus.CLARIFY
        assert outcome.message is not None and "Schumacher" in outcome.message
        assert llm.prompts == []

    async def test_the_models_reason_is_final_when_it_cannot_answer(self) -> None:
        runner = Runner()
        llm = ScriptedLLM(query(None, "Weather is not stored.", kind="other"))

        outcome = await agent(llm, runner).answer("Was it wet?", entities())

        assert outcome.status is SqlStatus.CANNOT_ANSWER
        assert outcome.message == "Weather is not stored."
        assert runner.ran == []
        assert len(llm.prompts) == 1


class TestRecovery:
    async def test_a_database_error_is_fed_back_and_the_correction_runs(self) -> None:
        llm = ScriptedLLM(query("SELECT nope FROM laps"), query("SELECT 1"))
        runner = Runner('column "nope" does not exist')

        outcome = await agent(llm, runner).answer("?", entities())

        assert outcome.status is SqlStatus.ANSWERED
        assert outcome.sql == "SELECT 1"
        assert outcome.attempts == 2
        assert 'Your previous query failed: column "nope" does not exist' in llm.prompts[1]

    async def test_a_rejected_query_never_reaches_the_database(self) -> None:
        llm = ScriptedLLM(query("SELECT * FROM ingestion_jobs"), query("SELECT 1"))
        runner = Runner()

        outcome = await agent(llm, runner).answer("?", entities())

        assert outcome.status is SqlStatus.ANSWERED
        assert runner.ran == ["SELECT 1"]
        assert "table ingestion_jobs is not available" in llm.prompts[1]

    async def test_an_unfinished_answer_is_retried_with_a_keep_it_short_hint(self) -> None:
        # Seen live: gpt-oss reasons past its budget on "why" questions.
        llm = ScriptedLLM(LLMInvalidResponseError("max tokens"), query("SELECT 1"))

        outcome = await agent(llm).answer("Why did Ferrari struggle?", entities())

        assert outcome.status is SqlStatus.ANSWERED
        assert UNFINISHED_ANSWER in llm.prompts[1]

    async def test_attempts_are_bounded_and_the_last_reason_kept(self) -> None:
        llm = ScriptedLLM(query("SELECT a"), query("SELECT b"), query("SELECT c"))
        runner = Runner("error a", "error b", "error c")

        outcome = await agent(llm, runner).answer("?", entities())

        assert outcome.status is SqlStatus.FAILED
        assert outcome.attempts == 3
        assert outcome.sql == "SELECT c"
        assert outcome.message == "error c"
        assert len(llm.prompts) == 3

    async def test_only_unfinished_answers_still_fail_cleanly(self) -> None:
        unfinished = LLMInvalidResponseError("max tokens")
        llm = ScriptedLLM(unfinished, unfinished, unfinished)

        outcome = await agent(llm).answer("?", entities())

        assert outcome.status is SqlStatus.FAILED
        assert outcome.sql is None
        assert outcome.message == UNFINISHED_ANSWER

    async def test_a_rate_limit_is_not_retried_here(self) -> None:
        llm = ScriptedLLM(LLMRateLimitedError("quota", retry_after=3600))

        with pytest.raises(LLMRateLimitedError):
            await agent(llm).answer("?", entities())

        assert len(llm.prompts) == 1
