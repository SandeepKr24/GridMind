"""From resolved entities to query rows, for questions about stored sessions.

    entities -> ids (session_context) -> SQL (sql_generator) -> rows (executor)

One attempt, no recovery: step 15 adds statement validation in front of the
executor and the bounded retry loop around generation. Callers run the
ingestion gate first; by the time this runs, every session is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.agent.entities import ResolvedEntities
from app.agent.executor import QueryFailedError, QueryResult, QueryRunner
from app.agent.session_context import (
    ContextProblem,
    SessionContext,
    SessionDirectory,
    build_context,
)
from app.agent.sql_generator import QueryType, generate_sql
from app.llm import LLMProvider


class SqlStatus(StrEnum):
    #: Rows came back (possibly none; an empty result is still an answer).
    ANSWERED = "answered"
    #: A name did not match anyone in the session. Ask the user.
    CLARIFY = "clarify"
    #: The model judged the stored data unable to answer.
    CANNOT_ANSWER = "cannot_answer"
    #: The query failed in the database.
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SqlOutcome:
    status: SqlStatus
    query_type: QueryType = QueryType.OTHER
    context: SessionContext | None = None
    sql: str | None = None
    result: QueryResult | None = None
    #: For CLARIFY and CANNOT_ANSWER: text for the user. For FAILED: the
    #: database's error, for the recovery loop, not for the user.
    message: str | None = None


class SqlAgent:
    def __init__(self, llm: LLMProvider, directory: SessionDirectory, runner: QueryRunner) -> None:
        self._llm = llm
        self._directory = directory
        self._runner = runner

    async def answer(self, question: str, entities: ResolvedEntities) -> SqlOutcome:
        context = await build_context(self._directory, entities)
        if isinstance(context, ContextProblem):
            return SqlOutcome(SqlStatus.CLARIFY, message=context.message)

        query = await generate_sql(self._llm, question, context)
        if query.sql is None:
            return SqlOutcome(
                SqlStatus.CANNOT_ANSWER,
                query.query_type,
                context,
                message=query.cannot_answer,
            )

        try:
            result = await self._runner.run(query.sql)
        except QueryFailedError as error:
            return SqlOutcome(
                SqlStatus.FAILED, query.query_type, context, query.sql, message=str(error)
            )
        return SqlOutcome(SqlStatus.ANSWERED, query.query_type, context, query.sql, result)
