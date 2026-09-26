"""Per-client limits on the three endpoints that spend money.

The limiter is tested against a fake clock. The route tests use apps with no
chat agent and no report writer, so every request fails fast with a 503 and no
LLM or database is involved: what is under test is only whether the limit
runs before the handler, and which endpoints it guards.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.rate_limit import RateLimiter
from app.config import Settings
from app.main import create_app
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


class TestRateLimiter:
    def test_allows_up_to_the_limit_then_refuses(self, clock: Clock) -> None:
        limiter = RateLimiter(2, 60, clock=clock)

        assert limiter.check("a") is None
        assert limiter.check("a") is None
        assert limiter.check("a") == pytest.approx(60)

    def test_the_wait_is_until_the_oldest_request_leaves_the_window(self, clock: Clock) -> None:
        limiter = RateLimiter(2, 60, clock=clock)
        limiter.check("a")
        clock.now += 20
        limiter.check("a")
        clock.now += 10

        assert limiter.check("a") == pytest.approx(30)

    def test_the_window_slides(self, clock: Clock) -> None:
        limiter = RateLimiter(1, 60, clock=clock)
        limiter.check("a")
        clock.now += 60

        assert limiter.check("a") is None

    def test_refused_requests_do_not_extend_the_wait(self, clock: Clock) -> None:
        # A client hammering the endpoint still gets in once Retry-After passes.
        limiter = RateLimiter(1, 60, clock=clock)
        limiter.check("a")
        for _ in range(5):
            clock.now += 10
            assert limiter.check("a") is not None
        clock.now += 10

        assert limiter.check("a") is None

    def test_clients_are_counted_separately(self, clock: Clock) -> None:
        limiter = RateLimiter(1, 60, clock=clock)
        limiter.check("a")

        assert limiter.check("b") is None
        assert limiter.check("a") is not None

    def test_memory_is_bounded_by_forgetting_the_least_recent_client(self, clock: Clock) -> None:
        limiter = RateLimiter(1, 60, max_clients=2, clock=clock)
        limiter.check("a")
        limiter.check("b")
        limiter.check("a")  # refused, but "a" is now the most recent
        limiter.check("c")  # evicts "b"

        assert limiter.check("a") is not None
        assert limiter.check("b") is None


def _client(limit: int) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=WRITER,
        database_url_readonly=READER,
        rate_limit_chat_per_minute=limit,
        rate_limit_ingest_per_hour=limit,
        rate_limit_report_per_hour=limit,
    )
    app = create_app(
        settings=settings,
        database=DatabaseDouble(),  # type: ignore[arg-type]
        schedules=SchedulesDouble(()),
    )
    return TestClient(app)


@pytest.fixture
def http() -> Iterator[TestClient]:
    with _client(2) as client:
        yield client


# The season is outside the supported range, so ingest answers 404 without
# touching the job store.
REQUESTS = {
    "chat": ("/api/chat", {"message": "Who won at Spa?"}),
    "ingest": ("/api/ingest", {"season_year": 1990, "round_number": 1, "session_type": "race"}),
    "report": ("/api/races/2024-14/report/generate", None),
}


class TestGuardedEndpoints:
    @pytest.mark.parametrize("name", REQUESTS)
    def test_the_request_past_the_limit_is_429_with_retry_after(
        self, http: TestClient, name: str
    ) -> None:
        path, body = REQUESTS[name]
        for _ in range(2):
            assert http.post(path, json=body).status_code != 429

        response = http.post(path, json=body)

        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0

    def test_each_endpoint_has_its_own_budget(self, http: TestClient) -> None:
        chat_path, chat_body = REQUESTS["chat"]
        for _ in range(3):
            http.post(chat_path, json=chat_body)

        report_path, _ = REQUESTS["report"]
        assert http.post(report_path).status_code != 429

    def test_a_refused_request_never_reaches_the_handler(self, http: TestClient) -> None:
        # Without an agent the handler answers 503; a 429 means it never ran.
        path, body = REQUESTS["chat"]
        statuses = [http.post(path, json=body).status_code for _ in range(3)]

        assert statuses == [503, 503, 429]

    def test_reads_are_not_limited(self, http: TestClient) -> None:
        for _ in range(10):
            assert http.get("/health").status_code != 429
