"""One chat question, from text to reply.

    resolve -> unsupported?  -> fixed reply
            -> standings?    -> standings adapter -> answer
            -> ingestion gate: refused   -> the gate's message
                               ingesting -> job id; the frontend asks again
                               ready     -> SQL agent -> answer

Resolving also rewrites the message to stand alone, using the previous turn
("2026" after "Which year's Monza do you mean?" becomes the whole question).
Everything after it works from that rewrite, never from the raw message.

Only three steps cost tokens: resolving, writing SQL, and writing the answer.
Everything that can be said without the model is: clarifications, refusals,
"the data cannot answer this", and failures.

Errors the user should retry (rate limits, outages, a full ingestion queue,
an unreachable calendar) propagate to the API layer, which knows the HTTP
status for each.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.agent.answer_generator import AnswerTable, build_table, generate_answer
from app.agent.conversations import Conversation, ResolvedQuestion, Turn
from app.agent.entities import Intent, Resolution, ResolvedEntities
from app.agent.ingestion_gate import GateDecision, GateStatus
from app.agent.sql_agent import SqlOutcome, SqlStatus
from app.ingestion.standings_provider import StandingsUnavailableError
from app.ingestion.standings_service import SeasonOutOfRangeError, StandingsResult
from app.ingestion.standings_store import ConstructorStandingRow, DriverStandingRow
from app.llm import LLMProvider

UNSUPPORTED = (
    "I can only answer questions about Formula 1 race data from 2018 onwards: results, "
    "lap times, tyres, pit stops, race control messages and championship standings."
)
COULD_NOT_QUERY = (
    "I couldn't build a working query for that question. Try asking it more simply, "
    "or about one specific thing, such as a driver's finishing position or lap times."
)
STANDINGS_DOWN = "The championship standings are unavailable right now. Try again later."

_TEAM_WORDS = re.compile(r"\b(constructors?|teams?)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ChatReply:
    answer: str
    table: AnswerTable | None = None
    sources: tuple[str, ...] = ()
    query_type: str | None = None
    #: What the question was understood to be about, when anything was.
    entities: ResolvedEntities | None = None
    #: Set while the data is being fetched; the frontend polls it.
    job_id: str | None = None
    clarifying_question: str | None = None
    #: The question was understood but turned down (season-wide, not run
    #: yet, too many sessions). Shown to the user, never inherited by a
    #: follow-up.
    refused: bool = False


class Resolver(Protocol):
    async def resolve(
        self,
        question: str,
        previous: ResolvedEntities | None = None,
        earlier: Turn | None = None,
    ) -> Resolution: ...


class Gate(Protocol):
    async def check(self, entities: ResolvedEntities) -> GateDecision: ...


class SqlAnswerer(Protocol):
    async def answer(self, question: str, entities: ResolvedEntities) -> SqlOutcome: ...


class Standings(Protocol):
    async def drivers(self, season: int) -> StandingsResult[DriverStandingRow]: ...
    async def constructors(self, season: int) -> StandingsResult[ConstructorStandingRow]: ...


def data_note(entities: ResolvedEntities) -> str:
    """Where the rows came from, and what was assumed to get there."""
    parts = []
    for session in entities.sessions:
        part = f"the {session.describe()}"
        if session.year_inferred:
            part += f" (the {session.year} season was assumed; the question gave no year)"
        parts.append(part)
    return "; ".join(parts)


def _clarify(question: str) -> ChatReply:
    return ChatReply(answer=question, clarifying_question=question)


class ChatAgent:
    def __init__(
        self,
        llm: LLMProvider,
        resolver: Resolver,
        gate: Gate,
        sql: SqlAnswerer,
        standings: Standings,
    ) -> None:
        self._llm = llm
        self._resolver = resolver
        self._gate = gate
        self._sql = sql
        self._standings = standings

    async def ask(self, message: str, conversation: Conversation) -> ChatReply:
        question, reply = await self._reply(message, conversation)
        # A fetch in progress is not an answer; the question comes back later.
        if reply.job_id is None:
            clarifying = reply.clarifying_question is not None
            remembered = None if clarifying or reply.refused else reply.entities
            conversation.record(Turn(question, reply.answer, remembered, clarifying))
        return reply

    async def _reply(self, message: str, conversation: Conversation) -> tuple[str, ChatReply]:
        """The question as understood, and the reply to it."""
        pending = conversation.take_pending(message)
        if pending is not None:
            return pending.question, await self._answer(message, pending, conversation)

        resolution = await self._resolver.resolve(
            message, conversation.previous_entities(), conversation.last_turn()
        )
        question = resolution.question or message
        if resolution.clarifying_question is not None:
            return question, _clarify(resolution.clarifying_question)
        assert resolution.entities is not None
        resolved = ResolvedQuestion(question, resolution.entities)
        return question, await self._answer(message, resolved, conversation)

    async def _answer(
        self, message: str, resolved: ResolvedQuestion, conversation: Conversation
    ) -> ChatReply:
        question, entities = resolved.question, resolved.entities
        if entities.intent is Intent.UNSUPPORTED:
            return ChatReply(answer=UNSUPPORTED)
        if entities.intent is Intent.STANDINGS:
            return await self._standings_reply(question, entities)

        decision = await self._gate.check(entities)
        if decision.status is GateStatus.REFUSED:
            return ChatReply(
                answer=decision.message or UNSUPPORTED, entities=entities, refused=True
            )
        if decision.status is GateStatus.INGESTING:
            # The frontend re-sends the raw message once the fetch lands.
            conversation.remember_pending(message, resolved)
            fetching = ", ".join(f"the {s.describe()}" for s in decision.waiting_on)
            return ChatReply(
                answer=f"Fetching the timing data for {fetching}. This can take a minute.",
                entities=entities,
                job_id=decision.job_id,
            )
        return await self._sql_reply(question, entities)

    async def _sql_reply(self, question: str, entities: ResolvedEntities) -> ChatReply:
        outcome = await self._sql.answer(question, entities)
        query_type = outcome.query_type.value
        if outcome.status is SqlStatus.CLARIFY:
            return _clarify(outcome.message or "Which driver or team do you mean?")
        if outcome.status is SqlStatus.CANNOT_ANSWER:
            reason = outcome.message or "the stored timing data does not cover it"
            return ChatReply(
                answer=f"I can't answer that from the stored timing data: {reason}",
                entities=entities,
                query_type=query_type,
            )
        if outcome.status is SqlStatus.FAILED or outcome.result is None:
            return ChatReply(answer=COULD_NOT_QUERY, entities=entities, query_type=query_type)

        table = build_table(outcome.result.columns, outcome.result.rows)
        note = data_note(entities)
        answer = await generate_answer(
            self._llm, question, note, table, truncated=outcome.result.truncated
        )
        sources = tuple(f"FastF1 timing data: {s.describe()}" for s in entities.sessions)
        return ChatReply(answer, table, sources, query_type, entities)

    async def _standings_reply(self, question: str, entities: ResolvedEntities) -> ChatReply:
        assert entities.year is not None  # the resolver always sets it for standings
        year = entities.year
        teams = bool(entities.constructors) or bool(_TEAM_WORDS.search(question))
        try:
            round_number, is_stale, table = await self._standings_table(year, teams=teams)
        except SeasonOutOfRangeError:
            return ChatReply(answer=f"There was no Formula 1 championship in {year}.")
        except StandingsUnavailableError:
            return ChatReply(answer=STANDINGS_DOWN, entities=entities)

        kind = "constructors'" if teams else "drivers'"
        after = f"after round {round_number}" if round_number else "before the first race"
        note = f"the {year} {kind} championship standings {after}"
        if entities.year_inferred:
            note += f" (the {year} season was assumed; the question gave no year)"
        if is_stale:
            note += " (these may be out of date: the latest refresh failed)"
        answer = await generate_answer(self._llm, question, note, table)
        source = f"jolpica-f1 championship standings, {year} {after}"
        return ChatReply(answer, table, (source,), "standings", entities)

    async def _standings_table(
        self, year: int, *, teams: bool
    ) -> tuple[int | None, bool, AnswerTable]:
        if teams:
            constructors = await self._standings.constructors(year)
            rows = [(r.position, r.constructor_name, r.points, r.wins) for r in constructors.rows]
            table = build_table(("position", "team", "points", "wins"), rows)
            return constructors.round_number, constructors.is_stale, table
        drivers = await self._standings.drivers(year)
        driver_rows = [
            (r.position, r.driver_name, r.constructor_name, r.points, r.wins) for r in drivers.rows
        ]
        table = build_table(("position", "driver", "team", "points", "wins"), driver_rows)
        return drivers.round_number, drivers.is_stale, table
