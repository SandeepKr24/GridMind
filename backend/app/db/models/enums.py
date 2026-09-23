"""Controlled vocabularies shared by the database, the API and the frontend.

These strings are a contract. `SessionType`, `JobStatus` and `JobStage` are
mirrored in `frontend/lib/api/types.ts`, and the Loading Pit binds one light per
`JobStage` value. Renaming a member here silently breaks that UI, so
`tests/test_enums.py` pins every value.

They are stored as native Postgres enums, which means a bad value is rejected
by the database rather than discovered later in a report.
"""

from __future__ import annotations

from enum import StrEnum


class SessionType(StrEnum):
    """Whole sessions only.

    Q1/Q2/Q3 and SQ1/SQ2/SQ3 are deliberately absent: qualifying is stored as
    one session, with the segment times kept as columns on the result row.
    """

    PRACTICE_1 = "practice_1"
    PRACTICE_2 = "practice_2"
    PRACTICE_3 = "practice_3"
    QUALIFYING = "qualifying"
    SPRINT = "sprint"
    SPRINT_QUALIFYING = "sprint_qualifying"
    RACE = "race"


class JobStatus(StrEnum):
    """Lifecycle of an ingestion job.

    `SKIPPED_CACHED` is a success: the data was already stored, so nothing was
    fetched. The frontend treats it as "done" without showing the Loading Pit.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_CACHED = "skipped_cached"


class JobStage(StrEnum):
    """The five Loading Pit lights, in order.

    The frontend advances a light only when the backend reports a new stage —
    never on a timer — so these must be emitted honestly and in sequence.
    Normalisation is not a stage; it happens inside `STORING`.
    """

    RESOLVING = "resolving"
    FETCHING = "fetching"
    STORING = "storing"
    VERIFYING = "verifying"
    ANSWERING = "answering"


class ReportType(StrEnum):
    SUMMARY = "summary"
    FULL = "full"


class ReportTrigger(StrEnum):
    """Why a report exists.

    Future races are reported automatically once their data lands; historic
    ones only when somebody asks, so we do not generate hundreds of reports
    nobody reads.
    """

    AUTOMATIC = "automatic"
    ON_REQUEST = "on_request"


#: Terminal statuses. A job in any of these is finished and holds no lock.
FINISHED_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.SKIPPED_CACHED})

#: Statuses that occupy the one-job-per-session slot.
ACTIVE_STATUSES = frozenset({JobStatus.PENDING, JobStatus.RUNNING})
