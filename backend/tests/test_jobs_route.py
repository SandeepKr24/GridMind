"""`POST /api/ingest` and `GET /api/jobs/{id}`, wired to a real `JobRunner`.

The store and provider are the in-memory doubles from `test_runner.py`, so
these tests cover the HTTP contract the frontend depends on
(`frontend/lib/api/jobs.ts`) without Postgres or FastF1.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models.enums import JobStatus
from app.ingestion.runner import JobRunner
from app.main import create_app
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble, event
from tests.test_runner import KEY, ProviderDouble, StoreDouble

TODAY = dt.datetime.now(dt.UTC).date()

#: Every field `IngestionJob` in frontend/lib/api/types.ts reads.
FRONTEND_FIELDS = {
    "id",
    "status",
    "stage",
    "progress_percent",
    "season_year",
    "round_number",
    "session_type",
    "started_at",
    "finished_at",
    "error_message",
    "rows_written",
}


class Harness:
    def __init__(self) -> None:
        self.store = StoreDouble()
        self.provider = ProviderDouble()
        self.runner = JobRunner(
            self.store, self.provider, max_concurrent=1, max_pending=1, timeout_seconds=5
        )
        schedules = SchedulesDouble(
            (
                event(1, dt.date(2024, 3, 2)),
                event(14, dt.date(2024, 7, 28)),
                # A round that has not been raced yet, whatever today is.
                event(20, TODAY + dt.timedelta(days=30)),
            )
        )
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, database_url=WRITER, database_url_readonly=READER
        )
        app = create_app(
            settings=settings,
            database=DatabaseDouble(),  # type: ignore[arg-type]
            schedules=schedules,
            runner=self.runner,
        )
        self.client = TestClient(app)

    def ingest(self, round_number: int = 14, **overrides: object) -> dict[str, object]:
        body: dict[str, object] = {
            "season_year": 2024,
            "round_number": round_number,
            "session_type": "race",
        }
        body.update(overrides)
        return body


@pytest.fixture
def harness() -> Iterator[Harness]:
    h = Harness()
    with h.client:
        yield h


class TestIngest:
    def test_accepts_and_returns_a_job_id(self, harness: Harness) -> None:
        response = harness.client.post("/api/ingest", json=harness.ingest())

        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert job_id in harness.store.jobs

    def test_force_re_ingests_a_stored_session(self, harness: Harness) -> None:
        harness.store.ingested.add(KEY)

        response = harness.client.post("/api/ingest", json=harness.ingest(force=True))
        harness.client.portal.call(harness.runner.wait_idle)  # type: ignore[union-attr]

        assert response.status_code == 202
        job = harness.store.jobs[response.json()["job_id"]]
        assert job.status == JobStatus.SUCCEEDED
        assert harness.provider.calls == [KEY]

    def test_without_force_a_stored_session_is_not_fetched(self, harness: Harness) -> None:
        harness.store.ingested.add(KEY)

        response = harness.client.post("/api/ingest", json=harness.ingest())

        job = harness.store.jobs[response.json()["job_id"]]
        assert job.status == JobStatus.SKIPPED_CACHED
        assert harness.provider.calls == []

    def test_a_round_not_on_the_calendar_is_404(self, harness: Harness) -> None:
        response = harness.client.post("/api/ingest", json=harness.ingest(round_number=9))
        assert response.status_code == 404
        assert harness.store.jobs == {}

    def test_a_race_that_has_not_run_is_refused(self, harness: Harness) -> None:
        # No timing data can exist, so a job would only burn a fetch slot.
        response = harness.client.post("/api/ingest", json=harness.ingest(round_number=20))
        assert response.status_code == 409
        assert harness.store.jobs == {}

    @pytest.mark.parametrize("season", [2017, TODAY.year + 1, 2099])
    def test_a_season_outside_the_supported_range_is_404(
        self, harness: Harness, season: int
    ) -> None:
        response = harness.client.post("/api/ingest", json=harness.ingest(season_year=season))
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "overrides",
        [{"session_type": "q1"}, {"round_number": 0}, {"round_number": "fourteen"}],
    )
    def test_a_malformed_request_is_422(
        self, harness: Harness, overrides: dict[str, object]
    ) -> None:
        response = harness.client.post("/api/ingest", json=harness.ingest(**overrides))
        assert response.status_code == 422

    def test_a_full_queue_is_503_with_retry_after(self, harness: Harness) -> None:
        harness.provider.gate.clear()
        harness.client.post("/api/ingest", json=harness.ingest(round_number=14))

        response = harness.client.post("/api/ingest", json=harness.ingest(round_number=1))
        harness.provider.gate.set()

        assert response.status_code == 503
        assert response.headers["retry-after"] == "60"


class TestJobStatus:
    def test_reports_every_field_the_frontend_reads(self, harness: Harness) -> None:
        job_id = harness.client.post("/api/ingest", json=harness.ingest()).json()["job_id"]
        harness.client.portal.call(harness.runner.wait_idle)  # type: ignore[union-attr]

        body = harness.client.get(f"/api/jobs/{job_id}").json()

        assert set(body) == FRONTEND_FIELDS
        assert body["id"] == job_id
        assert body["status"] == JobStatus.SUCCEEDED
        assert (body["season_year"], body["round_number"], body["session_type"]) == (
            2024,
            14,
            "race",
        )

    def test_an_unknown_job_is_404(self, harness: Harness) -> None:
        assert harness.client.get("/api/jobs/no-such-job").status_code == 404

    def test_a_malformed_id_never_reaches_the_store(self, harness: Harness) -> None:
        assert harness.client.get("/api/jobs/" + "x" * 65).status_code == 404
        assert harness.client.get("/api/jobs/bad%20id").status_code == 404
