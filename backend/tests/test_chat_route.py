"""`POST /api/chat`: the wire contract, conversations, and how failures reach the UI.

The chat agent is a double; what is under test is the route: the response
shape `frontend/lib/api/types.ts` expects, and the status codes
`frontend/lib/api/client.ts` handles specially.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.answer_generator import build_table
from app.agent.conversations import Conversation
from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.entity_resolver import CalendarUnavailableError
from app.agent.orchestrator import ChatReply
from app.api.routes import chat as chat_route
from app.config import Settings
from app.db.models.enums import SessionType
from app.ingestion.runner import IngestBusyError
from app.llm import LLMError, LLMRateLimitedError, LLMUnavailableError
from app.main import create_app
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
ANSWER = ChatReply(
    answer="Hamilton won.",
    table=build_table(("driver", "lap_time_ms"), [("Lewis Hamilton", 106000)]),
    sources=("FastF1 timing data: 2024 Belgian Grand Prix race",),
    query_type="result",
    entities=ResolvedEntities(Intent.SESSION, sessions=(SPA,), drivers=("Hamilton",)),
)


class AgentDouble:
    def __init__(self) -> None:
        self.reply: ChatReply = ANSWER
        self.error: Exception | None = None
        self.delay = 0.0
        self.asked: list[tuple[str, str]] = []

    async def ask(self, question: str, conversation: Conversation) -> ChatReply:
        self.asked.append((question, conversation.id))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.reply


def _app(agent: AgentDouble | None) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=WRITER, database_url_readonly=READER
    )
    app = create_app(
        settings=settings,
        database=DatabaseDouble(),  # type: ignore[arg-type]
        schedules=SchedulesDouble(()),
        chat=agent,  # type: ignore[arg-type]
    )
    return TestClient(app)


@pytest.fixture
def agent() -> AgentDouble:
    return AgentDouble()


@pytest.fixture
def http(agent: AgentDouble) -> Iterator[TestClient]:
    with _app(agent) as client:
        yield client


def ask(
    http: TestClient, message: str = "Who won at Spa 2024?", conversation: str | None = None
) -> httpx.Response:
    return http.post("/api/chat", json={"message": message, "conversation_id": conversation})


class TestContract:
    def test_an_answer_carries_every_field_the_frontend_reads(self, http: TestClient) -> None:
        body = ask(http).json()

        assert set(body) == {
            "answer",
            "data",
            "table",
            "sources",
            "query_type",
            "resolved_entities",
            "ingestion",
            "needs_clarification",
            "clarifying_question",
            "conversation_id",
        }
        assert body["answer"] == "Hamilton won."
        assert body["table"] == {
            "columns": ["driver", "lap time"],
            "rows": [["Lewis Hamilton", "1:46.000"]],
        }
        assert body["data"] == [{"driver": "Lewis Hamilton", "lap time": "1:46.000"}]
        assert body["resolved_entities"] == {
            "year": 2024,
            "round": 14,
            "grand_prix": "Belgian Grand Prix",
            "session_type": "race",
            "drivers": ["Hamilton"],
        }
        assert body["ingestion"] is None
        assert body["needs_clarification"] is False

    def test_a_fetch_in_progress_hands_over_its_job(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        agent.reply = ChatReply(answer="Fetching...", entities=ANSWER.entities, job_id="job-9")

        body = ask(http).json()

        assert body["ingestion"] == {"required": True, "job_id": "job-9"}
        assert body["table"] is None and body["data"] == []

    def test_a_clarifying_question_is_flagged(self, http: TestClient, agent: AgentDouble) -> None:
        agent.reply = ChatReply(answer="Which year?", clarifying_question="Which year?")

        body = ask(http).json()

        assert body["needs_clarification"] is True
        assert body["clarifying_question"] == "Which year?"
        assert body["resolved_entities"] is None

    def test_standings_entities_report_the_season_only(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        agent.reply = ChatReply(
            answer="Antonelli leads.", entities=ResolvedEntities(Intent.STANDINGS, year=2026)
        )

        entities = ask(http).json()["resolved_entities"]

        assert entities == {
            "year": 2026,
            "round": None,
            "grand_prix": None,
            "session_type": None,
            "drivers": [],
        }


class TestConversations:
    def test_a_new_conversation_is_created_and_can_be_continued(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        first = ask(http).json()["conversation_id"]
        second = ask(http, "And Leclerc?", first).json()["conversation_id"]

        assert first == second
        assert agent.asked[0][1] == agent.asked[1][1] == first

    def test_a_forgotten_conversation_is_404_so_the_page_starts_afresh(
        self, http: TestClient
    ) -> None:
        response = ask(http, conversation="forgotten-after-restart")

        assert response.status_code == 404

    @pytest.mark.parametrize("conversation", ["../etc", "x" * 65, "has space"])
    def test_a_malformed_conversation_id_is_rejected(
        self, http: TestClient, conversation: str
    ) -> None:
        assert ask(http, conversation=conversation).status_code == 422


class TestInput:
    @pytest.mark.parametrize("message", ["", "   ", "x" * 501])
    def test_blank_or_overlong_questions_are_rejected(
        self, http: TestClient, agent: AgentDouble, message: str
    ) -> None:
        assert ask(http, message).status_code == 422
        assert agent.asked == []

    def test_the_question_is_trimmed(self, http: TestClient, agent: AgentDouble) -> None:
        ask(http, "  Who won?  ")

        assert agent.asked[0][0] == "Who won?"


class TestFailures:
    def test_a_rate_limit_is_429_with_the_providers_wait(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        agent.error = LLMRateLimitedError("TPD", retry_after=12.3)

        response = ask(http)

        assert response.status_code == 429
        assert response.headers["retry-after"] == "13"
        assert "TPD" not in response.text

    def test_a_rate_limit_without_a_wait_suggests_a_minute(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        agent.error = LLMRateLimitedError("quota")

        assert ask(http).headers["retry-after"] == "60"

    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            (LLMUnavailableError("groq down"), "unavailable"),
            (IngestBusyError("full"), "busy"),
            (CalendarUnavailableError("fastf1"), "calendar"),
            (LLMError("groq rejected the API key"), "could not answer"),
        ],
    )
    def test_upstream_trouble_is_503_without_internal_detail(
        self, http: TestClient, agent: AgentDouble, error: Exception, detail: str
    ) -> None:
        agent.error = error

        response = ask(http)

        assert response.status_code == 503
        assert detail in response.json()["detail"]
        assert "retry-after" in response.headers
        assert "groq" not in response.text and "API key" not in response.text

    def test_an_unexpected_error_is_503_not_a_bare_500(
        self, http: TestClient, agent: AgentDouble
    ) -> None:
        agent.error = KeyError("session_id")

        response = ask(http)

        assert response.status_code == 503
        assert "session_id" not in response.text

    def test_a_question_past_the_deadline_is_503(
        self, http: TestClient, agent: AgentDouble, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(chat_route, "CHAT_DEADLINE_SECONDS", 0.05)
        agent.delay = 1.0

        response = ask(http)

        assert response.status_code == 503
        assert "too long" in response.json()["detail"]

    def test_without_an_llm_chat_is_503_and_the_rest_still_works(self) -> None:
        with _app(None) as client:
            response = ask(client)

            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]
            assert client.get("/health").status_code == 200

    def test_a_configured_llm_gets_a_real_chat_agent(self) -> None:
        from app.agent.orchestrator import ChatAgent
        from tests.test_sql_generator import FakeLLM

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, database_url=WRITER, database_url_readonly=READER
        )
        app = create_app(
            settings=settings,
            database=DatabaseDouble(),  # type: ignore[arg-type]
            schedules=SchedulesDouble(()),
            llm=FakeLLM("unused"),
        )
        with TestClient(app):
            assert isinstance(app.state.chat, ChatAgent)
            assert len(app.state.conversations) == 0

    def test_the_deadline_stays_under_the_frontends_timeout(self) -> None:
        # frontend/lib/api/chat.ts: timeoutMs 30_000.
        assert chat_route.CHAT_DEADLINE_SECONDS < 30
