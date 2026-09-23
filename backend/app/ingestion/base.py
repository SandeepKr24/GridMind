"""The boundary between a timing-data provider and the rest of the backend.

Nothing downstream of here knows that FastF1 exists. The provider returns these
frozen value objects; the normalizer maps them onto ORM rows. That separation
is what makes the pipeline testable without a network call, and what would let
a second provider be added without touching storage.

Durations are integer milliseconds and every optional field is genuinely
optional, because real sessions are full of gaps: a driver who never set a lap
time, a practice session with no pit data, a 2018 race with no tyre compounds.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol

from app.db.models.enums import SessionType


class ProviderError(RuntimeError):
    """The provider could not supply usable data.

    Raised for a session that does not exist, a payload that fails validation,
    and upstream failures alike. The job runner turns this into a failed job
    with a message the Loading Pit can show.
    """


class SessionNotAvailableError(ProviderError):
    """The session exists in the calendar but has no timing data yet.

    Distinct from an error: a future race, or one that finished minutes ago,
    is expected to be missing. The caller should say "not available yet"
    rather than "something went wrong".
    """


@dataclass(frozen=True, slots=True)
class RawEvent:
    """One Grand Prix weekend, as the provider describes it."""

    season: int
    round_number: int
    event_name: str
    official_name: str | None
    event_date: dt.date | None
    country: str | None
    location: str | None
    # "conventional", "sprint_qualifying", ... Decides which sessions exist.
    event_format: str | None
    # The session types this weekend actually has, in running order.
    sessions: tuple[SessionType, ...] = ()


@dataclass(frozen=True, slots=True)
class RawDriverEntry:
    """A driver as they appeared in one session.

    `driver_ref` is the stable identity across seasons; `code` and `number` are
    per-season and get reused, so neither can key a driver on its own.
    """

    driver_ref: str
    code: str | None
    number: int | None
    first_name: str | None
    last_name: str | None
    full_name: str
    nationality: str | None
    constructor_ref: str | None
    constructor_name: str | None


@dataclass(frozen=True, slots=True)
class RawResult:
    driver_ref: str
    position: int | None
    classified_position: str | None
    grid_position: int | None
    points: float | None
    status: str | None
    laps_completed: int | None
    q1_time_ms: int | None = None
    q2_time_ms: int | None = None
    q3_time_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RawLap:
    driver_ref: str
    lap_number: int
    lap_time_ms: int | None
    sector_1_ms: int | None
    sector_2_ms: int | None
    sector_3_ms: int | None
    speed_trap_kph: float | None
    position: int | None
    compound: str | None
    tyre_life: int | None
    is_personal_best: bool | None
    # "1" is clear; "4" is safety car, "2" yellow. A lap run behind a safety
    # car is not representative pace, and pace questions must exclude it.
    track_status: str | None
    stint: int | None = None
    # A deleted lap stood on track but was struck from the timing sheets.
    is_deleted: bool = False
    is_accurate: bool = True


@dataclass(frozen=True, slots=True)
class RawPitStop:
    driver_ref: str
    stop_number: int
    lap_number: int | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class RawRaceControlMessage:
    message: str
    timestamp: dt.datetime | None
    lap_number: int | None
    category: str | None
    flag: str | None
    scope: str | None
    driver_number: int | None


@dataclass(frozen=True, slots=True)
class RawSession:
    """Everything one ingestion job stores."""

    event: RawEvent
    session_type: SessionType
    session_date: dt.datetime | None
    drivers: tuple[RawDriverEntry, ...] = ()
    results: tuple[RawResult, ...] = ()
    laps: tuple[RawLap, ...] = ()
    pit_stops: tuple[RawPitStop, ...] = ()
    race_control: tuple[RawRaceControlMessage, ...] = ()
    #: Set when the session ran but the data looks partial — a session still in
    #: progress, or one the provider only half-covers. Stored, but not marked
    #: complete, so a later re-ingest will pick up the rest.
    is_partial: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def row_count(self) -> int:
        """Total rows this session contributes. Reported on the job."""
        return len(self.results) + len(self.laps) + len(self.pit_stops) + len(self.race_control)


class TimingProvider(Protocol):
    """What the ingestion pipeline needs from a data source."""

    def fetch_schedule(self, season: int) -> tuple[RawEvent, ...]:
        """The season calendar. Cheap enough to call on a page load."""
        ...

    def fetch_session(
        self, season: int, round_number: int, session_type: SessionType
    ) -> RawSession:
        """One session, whole.

        Slow — 30 to 120 seconds cold — which is the entire reason ingestion
        runs as a background job with a progress-reporting row.

        Raises `SessionNotAvailableError` if the session has no data yet, and
        `ProviderError` for anything else.
        """
        ...
