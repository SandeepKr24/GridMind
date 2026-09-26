"""Automatic post-race reports: which races, how often, and what it costs."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.db.models.enums import JobStage, JobStatus, ReportTrigger, SessionType
from app.ingestion.base import RawEvent
from app.ingestion.jobs import JobRecord
from app.reports.jobs import ReportBusyError
from app.reports.scheduler import MAX_WRITE_FAILURES, AutoReporter


def race(season: int, round_number: int, day: dt.date) -> RawEvent:
    return RawEvent(
        season=season,
        round_number=round_number,
        event_name=f"Round {round_number} Grand Prix",
        official_name=None,
        event_date=day,
        country=None,
        location=None,
        event_format=None,
    )


CALENDARS = {
    2025: (race(2025, 24, dt.date(2025, 12, 7)),),
    2026: (
        race(2026, 14, dt.date(2026, 9, 13)),
        race(2026, 15, dt.date(2026, 9, 26)),
        race(2026, 16, dt.date(2026, 10, 4)),
    ),
}


class Calendar:
    async def get(self, season: int) -> tuple[RawEvent, ...]:
        return CALENDARS.get(season, ())


class Reports:
    """Jobs finish at once, with `outcome` = (status, stage) of how they ended."""

    def __init__(self, *, busy: bool = False) -> None:
        self.busy = busy
        self.submitted: list[tuple[int, int, ReportTrigger]] = []
        self.outcome = (JobStatus.SUCCEEDED, JobStage.ANSWERING)
        self.records: dict[str, JobRecord] = {}

    async def submit(
        self, season: int, round_number: int, trigger: ReportTrigger = ReportTrigger.ON_REQUEST
    ) -> str:
        if self.busy:
            raise ReportBusyError("full")
        self.submitted.append((season, round_number, trigger))
        job_id = f"report-{round_number}-{len(self.submitted)}"
        status, stage = self.outcome
        self.records[job_id] = JobRecord(
            id=job_id,
            season_year=season,
            round_number=round_number,
            session_type=SessionType.RACE,
            status=status,
            stage=stage,
            progress_percent=None,
            started_at=None,
            finished_at=None,
            error_message=None,
            rows_written=None,
        )
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        return self.records.get(job_id)


class Archive:
    def __init__(self, existing: set[tuple[int, int]] | None = None) -> None:
        self.existing = existing or set()
        self.asked: list[tuple[int, int]] = []

    async def exists(self, season: int, round_number: int) -> bool:
        self.asked.append((season, round_number))
        return (season, round_number) in self.existing


def reporter(
    today: dt.date,
    *,
    reports: Reports | None = None,
    archive: Archive | None = None,
    window_days: int = 2,
) -> AutoReporter:
    return AutoReporter(
        Calendar(),
        reports or Reports(),
        archive or Archive(),
        window_days=window_days,
        today=lambda: today,
    )


class TestWhichRaces:
    async def test_the_day_after_a_race_it_is_picked_up(self) -> None:
        recent = await reporter(dt.date(2026, 9, 27)).recent_races()

        assert [e.round_number for e in recent] == [15]

    async def test_race_day_itself_is_too_early(self) -> None:
        # No results until hours after the flag; tomorrow's check gets it.
        assert await reporter(dt.date(2026, 9, 26)).recent_races() == []

    async def test_after_the_window_the_race_is_left_alone(self) -> None:
        assert await reporter(dt.date(2026, 9, 29)).recent_races() == []
        assert [e.round_number for e in await reporter(dt.date(2026, 9, 28)).recent_races()] == [15]

    async def test_historic_races_are_never_reported_automatically(self) -> None:
        recent = await reporter(dt.date(2026, 9, 27), window_days=2).recent_races()

        assert 14 not in [e.round_number for e in recent]

    async def test_the_window_reaches_back_into_last_season_in_january(self) -> None:
        recent = await reporter(dt.date(2026, 1, 1), window_days=30).recent_races()

        assert [(e.season, e.round_number) for e in recent] == [(2025, 24)]


class TestChecking:
    async def test_a_recent_race_without_a_report_gets_an_automatic_one(self) -> None:
        reports = Reports()

        started = await reporter(dt.date(2026, 9, 27), reports=reports).check_once()

        assert started == ["report-15-1"]
        assert reports.submitted == [(2026, 15, ReportTrigger.AUTOMATIC)]

    async def test_a_race_already_reported_is_skipped(self) -> None:
        reports = Reports()
        archive = Archive({(2026, 15)})

        started = await reporter(
            dt.date(2026, 9, 27), reports=reports, archive=archive
        ).check_once()

        assert started == []
        assert reports.submitted == []

    async def test_a_quiet_week_never_touches_the_database(self) -> None:
        # Every query wakes Neon's suspended compute, which costs money.
        archive = Archive()

        await reporter(dt.date(2026, 9, 20), archive=archive).check_once()

        assert archive.asked == []

    async def test_a_race_whose_results_are_not_out_is_retried_every_check(self) -> None:
        # Failing at the fetch costs no tokens; retrying is the point.
        reports = Reports()
        reports.outcome = (JobStatus.FAILED, JobStage.FETCHING)
        auto = reporter(dt.date(2026, 9, 27), reports=reports)

        for _ in range(4):
            await auto.check_once()

        assert len(reports.submitted) == 4

    async def test_a_race_whose_writing_keeps_failing_is_given_up_on(self) -> None:
        # Each writing failure spent a report's worth of tokens.
        reports = Reports()
        reports.outcome = (JobStatus.FAILED, JobStage.ANSWERING)
        auto = reporter(dt.date(2026, 9, 27), reports=reports)

        for _ in range(5):
            await auto.check_once()

        assert len(reports.submitted) == MAX_WRITE_FAILURES

    async def test_a_full_queue_is_left_for_the_next_check(self) -> None:
        started = await reporter(dt.date(2026, 9, 27), reports=Reports(busy=True)).check_once()

        assert started == []


class TestLoop:
    async def test_it_waits_then_checks_on_the_interval(self) -> None:
        reports = Reports()
        slept: list[float] = []

        async def sleep(seconds: float) -> None:
            slept.append(seconds)
            if len(slept) == 3:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await reporter(dt.date(2026, 9, 27), reports=reports).run(
                dt.timedelta(hours=3), sleep=sleep, first_delay=60
            )

        assert slept == [60, 3 * 3600, 3 * 3600]
        assert len(reports.submitted) == 2  # one per check; dedup is the job runner's

    async def test_a_failed_check_does_not_stop_the_loop(self) -> None:
        class BrokenArchive(Archive):
            async def exists(self, season: int, round_number: int) -> bool:
                raise ConnectionError("neon is waking up")

        checks = 0

        async def sleep(seconds: float) -> None:
            nonlocal checks
            checks += 1
            if checks == 3:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await reporter(dt.date(2026, 9, 27), archive=BrokenArchive()).run(
                dt.timedelta(hours=3), sleep=sleep, first_delay=0
            )

        assert checks == 3


class TestWiring:
    @pytest.mark.parametrize(
        ("enabled", "with_llm", "running"),
        [
            (True, True, True),
            (False, True, False),
            (True, False, False),
        ],
    )
    def test_the_loop_runs_only_when_enabled_and_an_llm_exists(
        self, enabled: bool, with_llm: bool, running: bool
    ) -> None:
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import create_app
        from tests.test_calendar_route import READER, WRITER, DatabaseDouble, SchedulesDouble
        from tests.test_sql_generator import FakeLLM

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            database_url=WRITER,
            database_url_readonly=READER,
            auto_report_enabled=enabled,
        )
        app = create_app(
            settings=settings,
            database=DatabaseDouble(),  # type: ignore[arg-type]
            schedules=SchedulesDouble(()),
            llm=FakeLLM("unused") if with_llm else None,
        )
        with TestClient(app):
            task = app.state.auto_reports
            assert (task is not None and not task.done()) is running
        # Stopped with the app.
        assert task is None or task.done()
