"""The enum values are a wire contract, so they are pinned.

`frontend/lib/api/types.ts` declares the same strings. The Loading Pit binds
one light to each `JobStage` value and the race list switches on
`SessionType`, so a rename here breaks the UI with no error anywhere — the
frontend would simply stop recognising what the backend sends.

These tests are deliberately literal. They are not restating the
implementation; they are restating the *frontend*, which is the other half of
the contract and cannot be imported from here.
"""

from __future__ import annotations

from app.db.models.enums import (
    ACTIVE_STATUSES,
    FINISHED_STATUSES,
    JobStage,
    JobStatus,
    ReportTrigger,
    ReportType,
    SessionType,
)


class TestSessionType:
    def test_matches_the_frontend_union(self) -> None:
        assert [s.value for s in SessionType] == [
            "practice_1",
            "practice_2",
            "practice_3",
            "qualifying",
            "sprint",
            "sprint_qualifying",
            "race",
        ]

    def test_qualifying_segments_are_not_session_types(self) -> None:
        # Segments are columns on the result row, not sessions. Adding them
        # here would change what "a session" means throughout ingestion.
        values = {s.value for s in SessionType}
        assert not values & {"q1", "q2", "q3", "sq1", "sq2", "sq3"}


class TestJobStage:
    def test_matches_the_loading_pit_lights_in_order(self) -> None:
        # Order matters: the Pit lights up stages left to right.
        assert [s.value for s in JobStage] == [
            "resolving",
            "fetching",
            "storing",
            "verifying",
            "answering",
        ]

    def test_there_are_exactly_five(self) -> None:
        # The Pit renders five lights. A sixth stage would have nowhere to go.
        assert len(JobStage) == 5

    def test_normalizing_is_not_a_stage(self) -> None:
        # The backend plan originally listed it; the frontend never had it.
        assert "normalizing" not in {s.value for s in JobStage}


class TestJobStatus:
    def test_matches_the_frontend_union(self) -> None:
        assert {s.value for s in JobStatus} == {
            "pending",
            "running",
            "succeeded",
            "failed",
            "skipped_cached",
        }

    def test_active_and_finished_partition_every_status(self) -> None:
        # A status in neither set would leak the per-session slot forever;
        # one in both would let a finished job block a new request.
        assert set(JobStatus) == ACTIVE_STATUSES | FINISHED_STATUSES
        assert not ACTIVE_STATUSES & FINISHED_STATUSES

    def test_a_cached_skip_counts_as_finished(self) -> None:
        # It is a success with no work done, not a failure.
        assert JobStatus.SKIPPED_CACHED in FINISHED_STATUSES


class TestReportEnums:
    def test_report_types(self) -> None:
        assert {r.value for r in ReportType} == {"summary", "full"}

    def test_triggers_distinguish_automatic_from_requested(self) -> None:
        assert {t.value for t in ReportTrigger} == {"automatic", "on_request"}


def test_every_enum_is_a_plain_string_at_the_boundary() -> None:
    """StrEnum members must serialise as their value, not `ClassName.MEMBER`.

    If these were plain `Enum`, JSON encoding would emit the repr and the
    frontend would receive `SessionType.RACE` instead of `race`.
    """
    assert f"{SessionType.RACE}" == "race"
    assert f"{JobStage.ANSWERING}" == "answering"
    assert SessionType.RACE == "race"
