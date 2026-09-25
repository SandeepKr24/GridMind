"""The ingestion gate: serve, fetch or refuse. No network, no database.

Most tests use a small recording runner. The concurrency and failure tests go
through the real `JobRunner` over the in-memory store from `test_runner.py`,
because "one job, not two" is the runner's guarantee and the gate must not
break it.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.entity_resolver import WHICH_RACE
from app.agent.ingestion_gate import GateStatus, IngestionGate, season_refusal
from app.db.models.enums import JobStatus, SessionType
from app.ingestion.base import ProviderError, SessionNotAvailableError
from app.ingestion.jobs import JobKey
from app.ingestion.runner import IngestBusyError, Submission
from tests.test_runner import KEY, ProviderDouble, StoreDouble, finished, runner

TODAY = dt.date(2026, 9, 25)


def session(
    round_number: int = 14,
    session_type: SessionType = SessionType.RACE,
    *,
    year: int = 2024,
    event_date: dt.date | None = dt.date(2024, 7, 28),
    name: str = "Belgian Grand Prix",
) -> ResolvedSession:
    return ResolvedSession(year, round_number, name, session_type, event_date)


def asking_about(*sessions: ResolvedSession) -> ResolvedEntities:
    return ResolvedEntities(intent=Intent.SESSION, sessions=sessions)


class RecordingRunner:
    def __init__(self, ingested: set[JobKey] | None = None) -> None:
        self.ingested = ingested or set()
        self.submitted: list[JobKey] = []
        self.busy = False

    async def is_ingested(self, key: JobKey) -> bool:
        return key in self.ingested

    async def submit(self, key: JobKey) -> Submission:
        if self.busy:
            raise IngestBusyError("full")
        self.submitted.append(key)
        return Submission(f"job-{len(self.submitted)}", is_new=True)


def gate(jobs: object, *, max_sessions: int = 2, today: dt.date = TODAY) -> IngestionGate:
    return IngestionGate(jobs, max_sessions=max_sessions, today=lambda: today)  # type: ignore[arg-type]


class TestServedFromStorage:
    async def test_a_stored_session_is_ready_without_a_job(self) -> None:
        jobs = RecordingRunner({KEY})

        decision = await gate(jobs).check(asking_about(session()))

        assert decision.status is GateStatus.READY
        assert decision.job_id is None
        assert jobs.submitted == []

    @pytest.mark.parametrize("intent", [Intent.STANDINGS, Intent.UNSUPPORTED])
    async def test_questions_needing_no_session_pass_straight_through(self, intent: Intent) -> None:
        jobs = RecordingRunner()

        decision = await gate(jobs).check(ResolvedEntities(intent=intent, year=2024))

        assert decision.status is GateStatus.READY
        assert jobs.submitted == []


class TestFetching:
    async def test_a_missing_session_starts_exactly_one_job(self) -> None:
        jobs = RecordingRunner()

        decision = await gate(jobs).check(asking_about(session()))

        assert decision.status is GateStatus.INGESTING
        assert decision.job_id == "job-1"
        assert decision.waiting_on == (session(),)
        assert jobs.submitted == [KEY]

    async def test_only_the_missing_sessions_are_fetched(self) -> None:
        qualifying = session(session_type=SessionType.QUALIFYING)
        jobs = RecordingRunner({KEY})

        decision = await gate(jobs).check(asking_about(session(), qualifying))

        assert decision.waiting_on == (qualifying,)
        assert jobs.submitted == [JobKey(2024, 14, SessionType.QUALIFYING)]

    async def test_two_missing_sessions_fetch_together_and_report_the_first(self) -> None:
        other = session(13, name="Hungarian Grand Prix", event_date=dt.date(2024, 7, 21))
        jobs = RecordingRunner()

        decision = await gate(jobs).check(asking_about(session(), other))

        assert decision.job_id == "job-1"
        assert len(jobs.submitted) == 2

    async def test_a_full_queue_after_one_fetch_started_still_reports_that_fetch(
        self,
    ) -> None:
        class FullAfterOne(RecordingRunner):
            async def submit(self, key: JobKey) -> Submission:
                self.busy = bool(self.submitted)
                return await super().submit(key)

        jobs = FullAfterOne()
        other = session(13, name="Hungarian Grand Prix", event_date=dt.date(2024, 7, 21))

        decision = await gate(jobs).check(asking_about(session(), other))

        assert decision.status is GateStatus.INGESTING
        assert decision.job_id == "job-1"
        assert jobs.submitted == [KEY]

    async def test_a_full_queue_is_left_to_the_api_to_report(self) -> None:
        jobs = RecordingRunner()
        jobs.busy = True

        with pytest.raises(IngestBusyError):
            await gate(jobs).check(asking_about(session()))


class TestRefusals:
    async def test_a_season_wide_question_is_refused_with_a_suggestion(self) -> None:
        jobs = RecordingRunner()

        decision = await gate(jobs).check(ResolvedEntities(intent=Intent.SEASON, year=2024))

        assert decision.status is GateStatus.REFUSED
        assert decision.message == season_refusal(2024)
        assert "2024 championship standings" in (decision.message or "")
        assert jobs.submitted == []

    async def test_a_session_question_with_no_session_asks_which_race(self) -> None:
        decision = await gate(RecordingRunner()).check(ResolvedEntities(intent=Intent.SESSION))

        assert decision.status is GateStatus.REFUSED
        assert decision.message == WHICH_RACE

    def test_a_season_refusal_without_a_year_still_reads_well(self) -> None:
        assert "a whole season" in season_refusal(None)

    async def test_more_sessions_than_the_budget_is_refused(self) -> None:
        jobs = RecordingRunner()
        three = asking_about(session(12), session(13), session(14))

        decision = await gate(jobs, max_sessions=2).check(three)

        assert decision.status is GateStatus.REFUSED
        assert decision.message == (
            "That question covers 3 sessions, and I can look at up to 2 per question. "
            "Try asking about fewer races or sessions."
        )
        assert jobs.submitted == []

    async def test_a_race_that_has_not_run_is_refused_with_its_date(self) -> None:
        upcoming = session(
            15, year=2026, name="Azerbaijan Grand Prix", event_date=dt.date(2026, 9, 26)
        )
        jobs = RecordingRunner()

        decision = await gate(jobs).check(asking_about(upcoming))

        assert decision.status is GateStatus.REFUSED
        assert decision.message == (
            "The 2026 Azerbaijan Grand Prix race hasn't run yet; "
            "it is scheduled for 26 September 2026."
        )
        assert jobs.submitted == []

    async def test_practice_of_an_upcoming_weekend_is_refused_without_a_date(self) -> None:
        practice = session(
            16,
            SessionType.PRACTICE_1,
            year=2026,
            name="Bahrain Grand Prix",
            event_date=dt.date(2026, 10, 4),
        )

        decision = await gate(RecordingRunner()).check(asking_about(practice))

        assert decision.message == "The 2026 Bahrain Grand Prix first practice hasn't run yet."

    async def test_practice_during_race_weekend_is_allowed(self) -> None:
        practice = session(
            15,
            SessionType.PRACTICE_1,
            year=2026,
            name="Azerbaijan Grand Prix",
            event_date=dt.date(2026, 9, 26),
        )

        decision = await gate(RecordingRunner()).check(asking_about(practice))

        assert decision.status is GateStatus.INGESTING

    async def test_an_undated_session_gets_the_benefit_of_the_doubt(self) -> None:
        decision = await gate(RecordingRunner()).check(asking_about(session(event_date=None)))

        assert decision.status is GateStatus.INGESTING


class TestWithTheRealRunner:
    async def test_concurrent_identical_questions_produce_one_job(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        provider.gate.clear()  # hold the fetch so both questions overlap it
        jobs = runner(store, provider)
        question = asking_about(session())

        first, second = await asyncio.gather(gate(jobs).check(question), gate(jobs).check(question))
        provider.gate.set()
        await jobs.wait_idle()

        assert first.job_id == second.job_id
        assert len(store.jobs) == 1
        assert provider.calls == [KEY]

    async def test_a_repeat_question_after_ingestion_needs_no_fetch(self) -> None:
        store, provider = StoreDouble(), ProviderDouble()
        jobs = runner(store, provider)
        question = asking_about(session())

        started = await gate(jobs).check(question)
        assert started.job_id is not None
        await finished(store, jobs, started.job_id)
        repeat = await gate(jobs).check(question)

        assert repeat.status is GateStatus.READY
        assert provider.calls == [KEY]
        # A cached answer writes no job row, unlike POST /api/ingest.
        assert len(store.jobs) == 1

    async def test_a_failed_fetch_leaves_a_distinct_message_on_its_job(self) -> None:
        store = StoreDouble()
        provider = ProviderDouble(error=SessionNotAvailableError("no timing data yet"))
        jobs = runner(store, provider)

        decision = await gate(jobs).check(asking_about(session()))
        assert decision.job_id is not None
        record = await finished(store, jobs, decision.job_id)

        # The Loading Pit shows this; the frontend does not re-ask on failure.
        assert record.status is JobStatus.FAILED
        assert record.error_message == "No timing data yet."

    async def test_asking_again_after_a_failure_starts_a_fresh_attempt(self) -> None:
        store = StoreDouble()
        provider = ProviderDouble(error=ProviderError("upstream down"))
        jobs = runner(store, provider)
        question = asking_about(session())

        first = await gate(jobs).check(question)
        assert first.job_id is not None
        await finished(store, jobs, first.job_id)
        provider.error = None
        retry = await gate(jobs).check(question)

        assert retry.status is GateStatus.INGESTING
        assert retry.job_id != first.job_id
