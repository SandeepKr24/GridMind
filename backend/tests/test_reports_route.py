"""Report endpoints and the report branch of `GET /api/jobs/{id}`.

The store is stubbed; `test_reports_store.py` covers the SQL. What is under
test here is the contract `frontend/lib/api/reports.ts` relies on.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models.enums import JobStage, JobStatus, ReportTrigger, ReportType, SessionType
from app.ingestion.jobs import JobRecord
from app.main import create_app
from app.reports import store
from app.reports.jobs import ReportBusyError
from app.reports.store import StoredReport
from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble, event

STORED = StoredReport(
    id=7,
    season=2024,
    round_number=14,
    event_name="Belgian Grand Prix",
    report_type=ReportType.FULL,
    trigger=ReportTrigger.ON_REQUEST,
    model="openai/gpt-oss-20b",
    generated_at=dt.datetime(2026, 9, 26, 10, 5, tzinfo=dt.UTC),
    sections=[{"heading": "Race Overview", "body": "Hamilton won."}],
)
RUNNING = JobRecord(
    id="report-abc",
    season_year=2024,
    round_number=14,
    session_type=SessionType.RACE,
    status=JobStatus.RUNNING,
    stage=JobStage.ANSWERING,
    progress_percent=None,
    started_at=None,
    finished_at=None,
    error_message=None,
    rows_written=None,
)


class ReportsDouble:
    def __init__(self) -> None:
        self.submitted: list[tuple[int, int]] = []
        self.busy = False

    async def submit(self, season: int, round_number: int) -> str:
        if self.busy:
            raise ReportBusyError("full")
        self.submitted.append((season, round_number))
        return "report-abc"

    def get(self, job_id: str) -> JobRecord | None:
        return RUNNING if job_id == "report-abc" else None

    async def shutdown(self) -> None:
        return None


def _client(reports: ReportsDouble | None, events: tuple[Any, ...] = ()) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=WRITER, database_url_readonly=READER
    )
    app = create_app(
        settings=settings,
        database=DatabaseDouble(),  # type: ignore[arg-type]
        schedules=SchedulesDouble(events),
        reports=reports,  # type: ignore[arg-type]
    )
    return TestClient(app)


@pytest.fixture
def reports() -> ReportsDouble:
    return ReportsDouble()


@pytest.fixture
def http(reports: ReportsDouble, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def report_for_race(
        connection: Any, season: int, round_number: int
    ) -> StoredReport | None:
        return STORED if (season, round_number) == (2024, 14) else None

    async def report_by_id(connection: Any, report_id: int) -> StoredReport | None:
        return STORED if report_id == 7 else None

    monkeypatch.setattr(store, "report_for_race", report_for_race)
    monkeypatch.setattr(store, "report_by_id", report_by_id)
    past = (event(14, dt.date(2024, 7, 28)), event(24, dt.date(2099, 12, 1)))
    with _client(reports, past) as client:
        yield client


class TestReading:
    def test_a_races_report_matches_the_frontend_type(self, http: TestClient) -> None:
        body = http.get("/api/races/2024-14/report").json()

        assert body == {
            "id": "7",
            "race_id": "2024-14",
            "event_name": "Belgian Grand Prix",
            "season": 2024,
            "report_type": "full",
            "generated_at": "2026-09-26T10:05:00+00:00",
            "model": "openai/gpt-oss-20b",
            "trigger": "on_request",
            "sections": [{"heading": "Race Overview", "body": "Hamilton won."}],
        }

    def test_no_report_yet_is_404_which_the_page_treats_as_normal(self, http: TestClient) -> None:
        assert http.get("/api/races/2024-13/report").status_code == 404

    def test_a_report_by_id(self, http: TestClient) -> None:
        assert http.get("/api/reports/7").json()["race_id"] == "2024-14"

    @pytest.mark.parametrize("report_id", ["8", "abc", "1" * 20, "-1"])
    def test_unknown_or_malformed_ids_are_404(self, http: TestClient, report_id: str) -> None:
        assert http.get(f"/api/reports/{report_id}").status_code == 404


class TestGenerating:
    def test_a_past_race_gets_a_job_the_page_can_poll(
        self, http: TestClient, reports: ReportsDouble
    ) -> None:
        response = http.post("/api/races/2024-14/report/generate")

        assert response.status_code == 202
        assert response.json() == {"job_id": "report-abc"}
        assert reports.submitted == [(2024, 14)]

        job = http.get("/api/jobs/report-abc").json()
        assert (job["status"], job["stage"]) == ("running", "answering")

    def test_an_unknown_report_job_is_404(self, http: TestClient) -> None:
        assert http.get("/api/jobs/report-missing").status_code == 404

    def test_a_round_not_on_the_calendar_is_404(
        self, http: TestClient, reports: ReportsDouble
    ) -> None:
        assert http.post("/api/races/2024-30/report/generate").status_code == 404
        assert reports.submitted == []

    def test_a_race_not_run_yet_is_409(self, http: TestClient, reports: ReportsDouble) -> None:
        assert http.post("/api/races/2024-24/report/generate").status_code == 409
        assert reports.submitted == []

    def test_a_full_queue_is_503_with_retry_after(
        self, http: TestClient, reports: ReportsDouble
    ) -> None:
        reports.busy = True

        response = http.post("/api/races/2024-14/report/generate")

        assert response.status_code == 503
        assert response.headers["retry-after"] == "60"

    def test_without_an_llm_generation_is_503_and_reading_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def report_for_race(connection: Any, season: int, round_number: int) -> StoredReport:
            return STORED

        monkeypatch.setattr(store, "report_for_race", report_for_race)
        with _client(None) as client:
            assert client.post("/api/races/2024-14/report/generate").status_code == 503
            assert client.get("/api/races/2024-14/report").status_code == 200
