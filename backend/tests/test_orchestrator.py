"""One chat question through every path of the orchestrator. No network, no database."""

from __future__ import annotations

import datetime as dt

import pytest

from app.agent.conversations import Conversation, ConversationStore, Turn
from app.agent.entities import Intent, Resolution, ResolvedEntities, ResolvedSession
from app.agent.executor import QueryResult
from app.agent.ingestion_gate import GateDecision, GateStatus
from app.agent.orchestrator import (
    COULD_NOT_QUERY,
    STANDINGS_DOWN,
    UNSUPPORTED,
    ChatAgent,
    ChatReply,
)
from app.agent.sql_agent import SqlOutcome, SqlStatus
from app.agent.sql_generator import QueryType
from app.db.models.enums import SessionType
from app.ingestion.standings_provider import StandingsUnavailableError
from app.ingestion.standings_service import SeasonOutOfRangeError, StandingsResult
from app.ingestion.standings_store import ConstructorStandingRow, DriverStandingRow
from tests.test_sql_generator import FakeLLM

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
GUESSED = ResolvedSession(
    2026, 14, "Spanish Grand Prix", SessionType.RACE, dt.date(2026, 9, 13), year_inferred=True
)
ASKING_ABOUT_SPA = ResolvedEntities(Intent.SESSION, sessions=(SPA,), drivers=("Leclerc",))
READY = GateDecision(GateStatus.READY)
RESOLVED_SPA = Resolution.of(ASKING_ABOUT_SPA)
ROWS = QueryResult(("driver", "lap_time_ms"), (("Charles Leclerc", 109245),), False, 3)


MONZA = ResolvedSession(2026, 16, "Italian Grand Prix", SessionType.RACE, dt.date(2026, 9, 6))
AT_MONZA = ResolvedEntities(Intent.SESSION, sessions=(MONZA,))
MONZA_QUESTION = "Who gained the most positions at Monza?"
MONZA_2026 = "Who gained the most positions at Monza in 2026?"
WHICH_YEAR = "Which year's Monza do you mean?"


class Resolver:
    def __init__(self, *resolutions: Resolution) -> None:
        # One resolution per ask, in order; the last repeats.
        self.resolutions = list(resolutions)
        self.calls: list[tuple[str, ResolvedEntities | None]] = []
        self.earlier: list[Turn | None] = []

    async def resolve(
        self,
        question: str,
        previous: ResolvedEntities | None = None,
        earlier: Turn | None = None,
    ) -> Resolution:
        self.calls.append((question, previous))
        self.earlier.append(earlier)
        return self.resolutions.pop(0) if len(self.resolutions) > 1 else self.resolutions[0]


class Gate:
    def __init__(self, decision: GateDecision = READY) -> None:
        self.decision = decision

    async def check(self, entities: ResolvedEntities) -> GateDecision:
        return self.decision


class Sql:
    def __init__(self, outcome: SqlOutcome | None = None) -> None:
        self.outcome = outcome or SqlOutcome(
            SqlStatus.ANSWERED, QueryType.PACE, sql="SELECT 1", result=ROWS, attempts=1
        )
        self.questions: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.questions)

    async def answer(self, question: str, entities: ResolvedEntities) -> SqlOutcome:
        self.questions.append(question)
        return self.outcome


class Standings:
    def __init__(self, error: Exception | None = None, *, is_stale: bool = False) -> None:
        self.error = error
        self.is_stale = is_stale
        self.asked: list[str] = []

    async def drivers(self, season: int) -> StandingsResult[DriverStandingRow]:
        self.asked.append("drivers")
        if self.error:
            raise self.error
        row = DriverStandingRow(1, "antonelli", "Kimi Antonelli", "ANT", "Mercedes", 292.0, 8)
        return StandingsResult(season, 15, None, self.is_stale, [row])

    async def constructors(self, season: int) -> StandingsResult[ConstructorStandingRow]:
        self.asked.append("constructors")
        row = ConstructorStandingRow(1, "mercedes", "Mercedes", 503.0, 10)
        return StandingsResult(season, 15, None, self.is_stale, [row])


class Harness:
    def __init__(
        self,
        *resolutions: Resolution,
        gate: Gate | None = None,
        sql: Sql | None = None,
        standings: Standings | None = None,
    ) -> None:
        self.llm = FakeLLM("Leclerc averaged 1:49.245.")
        self.resolver = Resolver(*(resolutions or (RESOLVED_SPA,)))
        self.sql = sql or Sql()
        self.standings = standings or Standings()
        self.agent = ChatAgent(self.llm, self.resolver, gate or Gate(), self.sql, self.standings)
        self.conversation: Conversation = ConversationStore(
            ttl=dt.timedelta(hours=1), max_conversations=10
        ).create()

    async def ask(self, question: str = "How fast was Leclerc at Spa 2024?") -> ChatReply:
        return await self.agent.ask(question, self.conversation)


class TestAnswered:
    async def test_rows_become_a_formatted_table_and_prose(self) -> None:
        harness = Harness()

        reply = await harness.ask()

        assert reply.answer == "Leclerc averaged 1:49.245."
        assert reply.table is not None
        assert reply.table.rows == (("Charles Leclerc", "1:49.245"),)
        assert reply.sources == ("FastF1 timing data: 2024 Belgian Grand Prix race",)
        assert reply.query_type == "pace"
        assert reply.entities == ASKING_ABOUT_SPA

    async def test_the_model_is_told_the_season_was_assumed(self) -> None:
        guessed = ResolvedEntities(Intent.SESSION, sessions=(GUESSED,))
        harness = Harness(Resolution.of(guessed))

        await harness.ask("Who won the last race?")

        messages, _, _ = harness.llm.calls[0]
        assert "the 2026 season was assumed" in messages[1].content

    async def test_the_turn_is_remembered_for_a_follow_up(self) -> None:
        harness = Harness()

        await harness.ask()
        await harness.ask("And Norris?")

        assert harness.resolver.calls[1] == ("And Norris?", ASKING_ABOUT_SPA)


class TestContext:
    """The user's transcript: "2026" must complete the Monza question, not replace it."""

    def harness(self, *, gate: Gate | None = None) -> Harness:
        return Harness(
            Resolution.ask(WHICH_YEAR),
            Resolution(entities=AT_MONZA, question=MONZA_2026),
            gate=gate,
        )

    async def test_a_reply_to_a_clarification_answers_the_original_question(self) -> None:
        harness = self.harness()

        await harness.ask(MONZA_QUESTION)
        reply = await harness.ask("2026")

        assert harness.resolver.earlier[1] == Turn(MONZA_QUESTION, WHICH_YEAR, None, True)
        assert reply.entities == AT_MONZA
        # The SQL and answer models see the whole question, never "2026".
        assert harness.sql.questions == [MONZA_2026]
        messages, _, _ = harness.llm.calls[0]
        assert f"Question: {MONZA_2026}" in messages[1].content

    async def test_the_completed_question_is_what_the_next_turn_sees(self) -> None:
        harness = self.harness()

        await harness.ask(MONZA_QUESTION)
        await harness.ask("2026")
        await harness.ask("And Leclerc?")

        earlier = harness.resolver.earlier[2]
        assert earlier is not None
        assert (earlier.question, earlier.clarifying) == (MONZA_2026, False)
        assert harness.resolver.calls[2] == ("And Leclerc?", AT_MONZA)

    async def test_a_fetch_keeps_the_completed_question_for_the_re_ask(self) -> None:
        gate = Gate(GateDecision(GateStatus.INGESTING, job_id="job-9", waiting_on=(MONZA,)))
        harness = self.harness(gate=gate)

        await harness.ask(MONZA_QUESTION)
        fetching = await harness.ask("2026")
        gate.decision = READY
        # The frontend sends the same raw text again once the job lands.
        await harness.ask("2026")

        assert fetching.job_id == "job-9"
        assert len(harness.resolver.calls) == 2
        assert harness.sql.questions == [MONZA_2026]

    async def test_without_a_rewrite_the_message_is_used_as_it_is(self) -> None:
        harness = Harness()

        await harness.ask("How fast was Leclerc at Spa 2024?")

        assert harness.sql.questions == ["How fast was Leclerc at Spa 2024?"]
        assert harness.conversation.turns[0].question == "How fast was Leclerc at Spa 2024?"


class TestNoProseNeeded:
    async def test_a_clarifying_question_is_passed_back_and_not_remembered(self) -> None:
        harness = Harness(Resolution.ask("Which year's Silverstone do you mean?"))

        reply = await harness.ask("Who won at Silverstone?")

        assert reply.clarifying_question == "Which year's Silverstone do you mean?"
        assert reply.answer == reply.clarifying_question
        assert harness.llm.calls == []
        assert harness.conversation.previous_entities() is None
        assert harness.conversation.turns[-1].clarifying

    async def test_an_unsupported_question_gets_the_fixed_reply(self) -> None:
        harness = Harness(Resolution.of(ResolvedEntities(Intent.UNSUPPORTED)))

        reply = await harness.ask("Best pizza in Rome?")

        assert reply.answer == UNSUPPORTED
        assert harness.sql.calls == 0
        assert harness.llm.calls == []

    async def test_a_gate_refusal_is_the_answer(self) -> None:
        refusal = GateDecision(GateStatus.REFUSED, message="That needs every race of 2024.")
        harness = Harness(gate=Gate(refusal))

        reply = await harness.ask()

        assert reply.answer == "That needs every race of 2024."
        assert reply.refused
        assert harness.sql.calls == 0
        # A refused question is not context for the next one.
        assert harness.conversation.previous_entities() is None

    async def test_a_name_nobody_answers_to_becomes_a_clarification(self) -> None:
        clarify = SqlOutcome(SqlStatus.CLARIFY, message='No driver called "Schumacher" took part.')
        harness = Harness(sql=Sql(clarify))

        reply = await harness.ask()

        assert reply.clarifying_question == 'No driver called "Schumacher" took part.'

    async def test_the_models_reason_is_shown_when_the_data_cannot_answer(self) -> None:
        cannot = SqlOutcome(SqlStatus.CANNOT_ANSWER, message="weather is not stored.")
        harness = Harness(sql=Sql(cannot))

        reply = await harness.ask()

        assert reply.answer == (
            "I can't answer that from the stored timing data: weather is not stored."
        )
        assert harness.llm.calls == []

    async def test_a_failed_query_says_so_without_internal_detail(self) -> None:
        failed = SqlOutcome(SqlStatus.FAILED, message='column "nope" does not exist')
        harness = Harness(sql=Sql(failed))

        reply = await harness.ask()

        assert reply.answer == COULD_NOT_QUERY
        assert "nope" not in reply.answer


class TestIngestion:
    async def test_a_fetch_returns_its_job_and_the_re_ask_skips_the_resolver(self) -> None:
        fetching = GateDecision(GateStatus.INGESTING, job_id="job-7", waiting_on=(SPA,))
        gate = Gate(fetching)
        harness = Harness(gate=gate)

        first = await harness.ask()
        gate.decision = GateDecision(GateStatus.READY)
        second = await harness.ask()

        assert first.job_id == "job-7"
        assert first.answer == (
            "Fetching the timing data for the 2024 Belgian Grand Prix race. This can take a minute."
        )
        assert second.answer == "Leclerc averaged 1:49.245."
        assert len(harness.resolver.calls) == 1  # the re-ask reused the resolution
        # The fetch notice is not a turn; the answer is.
        assert [t.answer for t in harness.conversation.turns] == ["Leclerc averaged 1:49.245."]


class TestStandings:
    async def test_drivers_standings_are_tabled_and_sourced(self) -> None:
        entities = ResolvedEntities(Intent.STANDINGS, year=2026, year_inferred=True)
        harness = Harness(Resolution.of(entities))

        reply = await harness.ask("Who leads the championship?")

        assert reply.table is not None
        assert reply.table.columns == ("position", "driver", "team", "points", "wins")
        assert reply.table.rows == (("1", "Kimi Antonelli", "Mercedes", "292", "8"),)
        assert reply.sources == ("jolpica-f1 championship standings, 2026 after round 15",)
        assert reply.query_type == "standings"
        messages, _, _ = harness.llm.calls[0]
        assert "the 2026 season was assumed" in messages[1].content

    @pytest.mark.parametrize(
        "question", ["Which team leads the constructors' championship?", "Top teams in 2024?"]
    )
    async def test_team_questions_get_the_constructors_table(self, question: str) -> None:
        standings = Standings()
        harness = Harness(
            Resolution.of(ResolvedEntities(Intent.STANDINGS, year=2024)), standings=standings
        )

        reply = await harness.ask(question)

        assert standings.asked == ["constructors"]
        assert reply.table is not None and reply.table.columns[1] == "team"

    async def test_stale_standings_are_flagged_to_the_model(self) -> None:
        harness = Harness(
            Resolution.of(ResolvedEntities(Intent.STANDINGS, year=2024)),
            standings=Standings(is_stale=True),
        )

        await harness.ask("Who leads?")

        messages, _, _ = harness.llm.calls[0]
        assert "may be out of date" in messages[1].content

    async def test_no_championship_that_year(self) -> None:
        harness = Harness(
            Resolution.of(ResolvedEntities(Intent.STANDINGS, year=1949)),
            standings=Standings(SeasonOutOfRangeError("1949")),
        )

        reply = await harness.ask("Who won in 1949?")

        assert reply.answer == "There was no Formula 1 championship in 1949."

    async def test_standings_unavailable_is_said_plainly(self) -> None:
        harness = Harness(
            Resolution.of(ResolvedEntities(Intent.STANDINGS, year=2024)),
            standings=Standings(StandingsUnavailableError("jolpica down")),
        )

        reply = await harness.ask("Who leads?")

        assert reply.answer == STANDINGS_DOWN
        assert "jolpica" not in reply.answer
