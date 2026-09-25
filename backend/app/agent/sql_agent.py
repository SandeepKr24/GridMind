"""From resolved entities to query rows, with bounded recovery.

    entities -> ids (session_context) -> SQL (sql_generator)
             -> checked (sql_validator) -> rows (executor)

A query the validator rejects, or the database refuses, goes back to the
model with the reason, and the model tries again. So does a response the
model could not finish: gpt-oss sometimes reasons past its token budget on
open "why" questions, and the retry asks for the simplest query instead.

What is never retried, because a retry would cost tokens and change nothing:
- an empty result: a valid answer ("nobody was penalised");
- the model saying the data cannot answer: honest, and final;
- a rate limit or outage: the chat layer tells the user to try shortly.

Callers run the ingestion gate first; by the time this runs, every session is
stored.
"""

from __future__ import annotations

import logging
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
from app.agent.sql_generator import GeneratedQuery, QueryType, generate_sql
from app.agent.sql_validator import SqlRejectedError, validate_sql
from app.llm import LLMInvalidResponseError, LLMProvider

logger = logging.getLogger(__name__)

#: One try plus two corrections, as the plan asks (2-3 retries at most).
MAX_ATTEMPTS = 3

UNFINISHED_ANSWER = (
    "your previous answer was cut off or was not valid JSON. Write the simplest "
    "query that answers the question, and keep your reasoning short"
)


class SqlStatus(StrEnum):
    #: Rows came back (possibly none; an empty result is still an answer).
    ANSWERED = "answered"
    #: A name did not match anyone in the session. Ask the user.
    CLARIFY = "clarify"
    #: The model judged the stored data unable to answer.
    CANNOT_ANSWER = "cannot_answer"
    #: Every attempt failed. `message` holds the last reason, for logs only.
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SqlOutcome:
    status: SqlStatus
    query_type: QueryType = QueryType.OTHER
    context: SessionContext | None = None
    sql: str | None = None
    result: QueryResult | None = None
    #: For CLARIFY and CANNOT_ANSWER: text for the user. For FAILED: the last
    #: internal error, which is not fit to show.
    message: str | None = None
    #: How many generations it took, for logs and token accounting.
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class _Failure:
    """One attempt that went wrong, and what to tell the model about it."""

    feedback: str
    query: GeneratedQuery | None = None


class SqlAgent:
    def __init__(
        self,
        llm: LLMProvider,
        directory: SessionDirectory,
        runner: QueryRunner,
        *,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._llm = llm
        self._directory = directory
        self._runner = runner
        self._max_attempts = max_attempts

    async def answer(self, question: str, entities: ResolvedEntities) -> SqlOutcome:
        context = await build_context(self._directory, entities)
        if isinstance(context, ContextProblem):
            return SqlOutcome(SqlStatus.CLARIFY, message=context.message)

        failure: _Failure | None = None
        for attempt in range(1, self._max_attempts + 1):
            outcome = await self._attempt(question, context, failure, attempt)
            if isinstance(outcome, SqlOutcome):
                return outcome
            failure = outcome
            logger.warning(
                "sql attempt %d/%d failed: %s", attempt, self._max_attempts, failure.feedback
            )

        assert failure is not None  # the loop ran at least once
        last = failure.query
        return SqlOutcome(
            SqlStatus.FAILED,
            last.query_type if last else QueryType.OTHER,
            context,
            last.sql if last else None,
            message=failure.feedback,
            attempts=self._max_attempts,
        )

    async def _attempt(
        self,
        question: str,
        context: SessionContext,
        failure: _Failure | None,
        attempt: int,
    ) -> SqlOutcome | _Failure:
        try:
            query = await generate_sql(
                self._llm,
                question,
                context,
                previous_error=failure.feedback if failure else None,
            )
        except LLMInvalidResponseError:
            return _Failure(UNFINISHED_ANSWER)

        if query.sql is None:
            return SqlOutcome(
                SqlStatus.CANNOT_ANSWER,
                query.query_type,
                context,
                message=query.cannot_answer,
                attempts=attempt,
            )
        try:
            validate_sql(query.sql)
            result = await self._runner.run(query.sql)
        except (SqlRejectedError, QueryFailedError) as error:
            return _Failure(str(error), query)
        return SqlOutcome(
            SqlStatus.ANSWERED, query.query_type, context, query.sql, result, attempts=attempt
        )
