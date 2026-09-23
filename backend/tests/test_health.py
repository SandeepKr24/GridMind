"""Health endpoints.

The split between liveness and readiness is not ceremony here. Neon suspends
an idle compute after five minutes, and *any* query resets that timer. A
container host polling a database-backed health check every 30s would keep the
compute awake permanently and spend the free plan's 100 CU-hours per month on
nothing at all. So `/health` must never touch the database, and there is a test
below that fails if someone makes it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

WRITER = "postgresql://neondb_owner:pw@ep-x.aws.neon.tech/neondb"
READER = "postgresql://gridmind_readonly:pw2@ep-x.aws.neon.tech/neondb"


class DatabaseDouble:
    """Stands in for the real Database, and records whether it was used."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.ping_count = 0

    async def ping(self) -> bool:
        self.ping_count += 1
        if not self.healthy:
            raise ConnectionError("compute is suspended")
        return True

    async def dispose(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=WRITER,
        database_url_readonly=READER,
        cors_origins="http://localhost:3000",
    )


def build(settings: Settings, db: DatabaseDouble) -> TestClient:
    app = create_app(settings=settings, database=db)  # type: ignore[arg-type]
    return TestClient(app)


class TestLiveness:
    def test_returns_ok(self, settings: Settings) -> None:
        with build(settings, DatabaseDouble()) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_does_not_touch_the_database(self, settings: Settings) -> None:
        # The whole point. See the module docstring.
        db = DatabaseDouble()
        with build(settings, db) as client:
            client.get("/health")
            client.get("/health")
        assert db.ping_count == 0

    def test_still_ok_when_the_database_is_unreachable(self, settings: Settings) -> None:
        # Liveness answers "is the process alive", not "is Postgres up". If it
        # conflated the two, the host would restart a perfectly healthy
        # container every time Neon was mid-resume.
        with build(settings, DatabaseDouble(healthy=False)) as client:
            assert client.get("/health").status_code == 200


class TestReadiness:
    def test_reports_ready_when_the_database_answers(self, settings: Settings) -> None:
        db = DatabaseDouble()
        with build(settings, db) as client:
            response = client.get("/health/db")
        assert response.status_code == 200
        assert response.json()["database"] == "ok"
        assert db.ping_count == 1

    def test_reports_503_when_the_database_is_unreachable(self, settings: Settings) -> None:
        with build(settings, DatabaseDouble(healthy=False)) as client:
            response = client.get("/health/db")
        assert response.status_code == 503
        assert response.json()["database"] == "unreachable"

    def test_failure_does_not_leak_the_connection_string(self, settings: Settings) -> None:
        # Error bodies on a public API must not echo driver text, which
        # commonly contains host and user.
        with build(settings, DatabaseDouble(healthy=False)) as client:
            body = client.get("/health/db").text
        assert "neondb_owner" not in body
        assert "pw" not in body
        assert "neon.tech" not in body


class TestCors:
    def test_configured_origin_is_allowed(self, settings: Settings) -> None:
        with build(settings, DatabaseDouble()) as client:
            response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_unknown_origin_is_not_allowed(self, settings: Settings) -> None:
        with build(settings, DatabaseDouble()) as client:
            response = client.get("/health", headers={"Origin": "http://evil.test"})
        assert "access-control-allow-origin" not in response.headers


class TestLifecycle:
    def test_database_is_disposed_on_shutdown(self, settings: Settings) -> None:
        # Neon charges for compute time; connections left open past shutdown
        # delay the suspend.
        db = DatabaseDouble()
        disposed: list[bool] = []

        async def record() -> None:
            disposed.append(True)

        db.dispose = record  # type: ignore[method-assign]
        with build(settings, db) as client:
            client.get("/health")
        assert disposed == [True]
