"""The SQL agent's single pass: ids, then SQL, then rows. No network."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence

from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.executor import QueryFailedError, QueryResult
from app.agent.session_context import StoredSession
from app.agent.sql_agent import SqlAgent, SqlStatus
from app.agent.sql_generator import QueryType
from app.db.models.enums import SessionType
from tests.test_session_context import GRID
from tests.test_sql_generator import FakeLLM

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
ROWS = QueryResult(("full_name",), (("Lewis Hamilton",),), truncated=False, elapsed_ms=3)


class Directory:
    async def load(self, sessions: Sequence[ResolvedSession]) -> tuple[StoredSession, ...]:
        return tuple(StoredSession(57, s, GRID) for s in sessions)


class Runner:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.ran: list[str] = []

    async def run(self, sql: str) -> QueryResult:
        self.ran.append(sql)
        if self.error is not None:
            raise QueryFailedError(self.error)
        return ROWS


def entities(*drivers: str) -> ResolvedEntities:
    return ResolvedEntities(Intent.SESSION, sessions=(SPA,), drivers=drivers)


def reply(sql: str | None, reason: str | None = None, kind: str = "result") -> FakeLLM:
    return FakeLLM(json.dumps({"query_type": kind, "sql": sql, "cannot_answer": reason}))


async def test_rows_come_back_with_the_query_and_its_type() -> None:
    runner = Runner()

    outcome = await SqlAgent(reply("SELECT 1"), Directory(), runner).answer("Who won?", entities())

    assert outcome.status is SqlStatus.ANSWERED
    assert outcome.query_type is QueryType.RESULT
    assert outcome.sql == "SELECT 1"
    assert outcome.result == ROWS
    assert runner.ran == ["SELECT 1"]


async def test_an_unknown_driver_is_asked_about_before_any_llm_call() -> None:
    llm = reply("SELECT 1")

    outcome = await SqlAgent(llm, Directory(), Runner()).answer("?", entities("Schumacher"))

    assert outcome.status is SqlStatus.CLARIFY
    assert outcome.message is not None and "Schumacher" in outcome.message
    assert llm.calls == []


async def test_the_models_reason_is_passed_on_when_it_cannot_answer() -> None:
    runner = Runner()
    llm = reply(None, "Weather is not stored.", kind="other")

    outcome = await SqlAgent(llm, Directory(), runner).answer("Was it wet?", entities())

    assert outcome.status is SqlStatus.CANNOT_ANSWER
    assert outcome.message == "Weather is not stored."
    assert runner.ran == []


async def test_a_database_error_is_kept_for_the_recovery_step() -> None:
    llm = reply("SELECT nope")

    outcome = await SqlAgent(llm, Directory(), Runner('column "nope" does not exist')).answer(
        "?", entities()
    )

    assert outcome.status is SqlStatus.FAILED
    assert outcome.sql == "SELECT nope"
    assert outcome.message == 'column "nope" does not exist'


async def test_drivers_named_reach_the_prompt_as_ids() -> None:
    llm = reply("SELECT 1")

    await SqlAgent(llm, Directory(), Runner()).answer("Norris pace?", entities("Norris"))

    messages, _, _ = llm.calls[0]
    assert "Lando Norris (NOR) = driver_id 4" in messages[1].content
