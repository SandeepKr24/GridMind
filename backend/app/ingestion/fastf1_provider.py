"""FastF1 implementation of `TimingProvider`.

FastF1 is synchronous, pandas-based and slow on a cold cache, so everything
here blocks. The job runner calls it in a worker thread; nothing in this module
should be awaited directly from a request handler.

The persistent cache is not an optimisation. Without it every question about a
session re-downloads tens of megabytes, which is both slow and rude to the
upstream API.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.db.models.enums import SessionType
from app.ingestion.base import (
    ProviderError,
    RawDriverEntry,
    RawEvent,
    RawLap,
    RawPitStop,
    RawRaceControlMessage,
    RawResult,
    RawSession,
    SessionNotAvailableError,
)
from app.ingestion.convert import (
    duration_ms,
    to_bool,
    to_date,
    to_datetime,
    to_float,
    to_int,
    to_str,
)

logger = logging.getLogger(__name__)

#: FastF1 fills an unknown tyre with a placeholder string instead of leaving
#: it empty. Stored as-is, "None" would read as a sixth compound.
UNKNOWN_COMPOUNDS = frozenset({"NONE", "NAN", "UNKNOWN", "TEST_UNKNOWN"})


#: FIA wording for a single car: "CAR 4 (NOR) TIME 1:50.504 DELETED ...".
#: "CARS 23 (ALB) AND 4 (NOR)" does not match, and stays unattributed.
_ONE_CAR = re.compile(r"\bCAR (\d{1,2}) \([A-Z]{3}\)")


def car_in_message(message: str) -> int | None:
    """The car a penalty, deleted time or investigation is about.

    FastF1 only fills RacingNumber for driver-scoped flags, so without this
    every penalty would be stored with no driver, and "who was penalised?"
    would silently find nobody.
    """
    cars = {int(number) for number in _ONE_CAR.findall(message)}
    # "CAR 44 (HAM) AND CAR 1 (VER)" names two drivers; one row cannot.
    return cars.pop() if len(cars) == 1 else None


def _racing_number(row: Any, message: str) -> int | None:
    number = to_int(row.get("RacingNumber"))
    return number if number is not None else car_in_message(message)


def to_compound(value: Any) -> str | None:
    text = to_str(value)
    if text is None or text.upper() in UNKNOWN_COMPOUNDS:
        return None
    return text.upper()


#: Our session types to FastF1's session identifiers.
SESSION_IDENTIFIERS: dict[SessionType, str] = {
    SessionType.PRACTICE_1: "FP1",
    SessionType.PRACTICE_2: "FP2",
    SessionType.PRACTICE_3: "FP3",
    SessionType.QUALIFYING: "Q",
    SessionType.SPRINT: "S",
    SessionType.SPRINT_QUALIFYING: "SQ",
    SessionType.RACE: "R",
}

#: FastF1 schedule session names to our types. A weekend lists its sessions as
#: display names in `Session1`..`Session5`, and the names have changed across
#: seasons — "Sprint Shootout" became "Sprint Qualifying" in 2024.
SESSION_NAMES: dict[str, SessionType] = {
    "practice 1": SessionType.PRACTICE_1,
    "practice 2": SessionType.PRACTICE_2,
    "practice 3": SessionType.PRACTICE_3,
    "qualifying": SessionType.QUALIFYING,
    "sprint": SessionType.SPRINT,
    "sprint qualifying": SessionType.SPRINT_QUALIFYING,
    "sprint shootout": SessionType.SPRINT_QUALIFYING,
}

#: Only qualifying-type sessions carry segment times.
SEGMENT_SESSIONS = frozenset({SessionType.QUALIFYING, SessionType.SPRINT_QUALIFYING})
#: Sessions whose classification is decided by elapsed race time.
TIMED_SESSIONS = frozenset({SessionType.RACE, SessionType.SPRINT})


@dataclass(frozen=True, slots=True)
class FinishTime:
    gap_to_winner_ms: int | None
    race_time_ms: int | None


_NO_TIME = FinishTime(None, None)


def finishing_times(rows: Sequence[tuple[int | None, int | None, int | None]]) -> list[FinishTime]:
    """Gap to the winner and total race time, from (position, laps, Time) rows.

    FastF1's `Time` holds the winner's total race time and, for everyone else,
    their gap to the winner. That gap only means something for a car that
    completed the winner's laps: a lapped car's Time is still filled in
    (Sargeant, one lap down in Bahrain 2024, read +20.795s), so cars short
    of the winner's lap count get neither value, and the page shows "+1 LAP"
    from their lap count instead. Retired and disqualified cars have no Time.
    """
    winner = next((r for r in rows if r[0] == 1 and r[2] is not None), None)
    if winner is None:
        return [_NO_TIME for _ in rows]
    _, winner_laps, winner_time = winner
    assert winner_time is not None  # narrowed by the search above
    times: list[FinishTime] = []
    for position, laps, time_ms in rows:
        if position == 1:
            times.append(FinishTime(0, winner_time))
        elif time_ms is not None and laps is not None and laps == winner_laps:
            times.append(FinishTime(time_ms, winner_time + time_ms))
        else:
            times.append(_NO_TIME)
    return times


_cache_lock = threading.Lock()
_cache_enabled = False


def enable_cache(cache_dir: str) -> None:
    """Point FastF1 at a persistent cache directory. Safe to call repeatedly.

    Guarded by a lock because the job runner may start several ingestions at
    once, and FastF1's cache setup is process-global.
    """
    global _cache_enabled
    import fastf1

    with _cache_lock:
        if _cache_enabled:
            return
        path = Path(cache_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(path))
        _cache_enabled = True
        logger.info("FastF1 cache enabled at %s", path)


def _session_types_for(row: Any) -> tuple[SessionType, ...]:
    """Which sessions a weekend actually has.

    Read from the schedule rather than assumed, because sprint weekends differ
    from conventional ones and the format has changed repeatedly.
    """
    found: list[SessionType] = []
    for index in range(1, 6):
        name = to_str(row.get(f"Session{index}"))
        if name is None:
            continue
        session_type = SESSION_NAMES.get(name.strip().lower())
        if session_type is not None and session_type not in found:
            found.append(session_type)
    # "Race" is the fifth session on every weekend format.
    if SessionType.RACE not in found:
        found.append(SessionType.RACE)
    return tuple(found)


def _optional_frame(session: Any, attribute: str) -> Any:
    """A session frame that may not exist, as None rather than an exception.

    `Session.load()` can succeed partially. Seasons before 2018 resolve through
    Ergast, which supplies the classification but no timing, and FastF1 then
    *raises* `DataNotLoadedError` on `session.laps` rather than returning an
    empty frame. Without this the whole ingest fails on a session we could
    still store results for.
    """
    try:
        return getattr(session, attribute)
    except Exception:
        logger.debug("%s not loaded for this session", attribute)
        return None


def _event_from_row(season: int, row: Any) -> RawEvent:
    return RawEvent(
        season=season,
        round_number=to_int(row.get("RoundNumber")) or 0,
        event_name=to_str(row.get("EventName")) or "Unknown Grand Prix",
        official_name=to_str(row.get("OfficialEventName")),
        event_date=to_date(row.get("EventDate")),
        country=to_str(row.get("Country")),
        location=to_str(row.get("Location")),
        event_format=to_str(row.get("EventFormat")),
        sessions=_session_types_for(row),
    )


class FastF1Provider:
    """Reads sessions from FastF1. Blocking."""

    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = cache_dir

    # -- schedule ------------------------------------------------------

    def fetch_schedule(self, season: int) -> tuple[RawEvent, ...]:
        import fastf1

        enable_cache(self._cache_dir)
        try:
            schedule = fastf1.get_event_schedule(season, include_testing=False)
        except Exception as error:
            raise ProviderError(f"could not load the {season} calendar: {error}") from error

        try:
            events = [
                _event_from_row(season, row)
                for _, row in schedule.iterrows()
                # Round 0 is pre-season testing, which we do not store.
                if (to_int(row.get("RoundNumber")) or 0) > 0
            ]
        except Exception as error:
            # One unreadable row must reach callers as a provider failure they
            # can degrade on, not as an arbitrary pandas exception.
            raise ProviderError(f"could not read the {season} calendar: {error}") from error
        if not events:
            raise ProviderError(f"the {season} calendar is empty")
        return tuple(events)

    # -- one session ---------------------------------------------------

    def fetch_session(
        self, season: int, round_number: int, session_type: SessionType
    ) -> RawSession:
        import fastf1

        enable_cache(self._cache_dir)
        identifier = SESSION_IDENTIFIERS[session_type]

        try:
            session = fastf1.get_session(season, round_number, identifier)
        except Exception as error:
            raise SessionNotAvailableError(
                f"{season} round {round_number} {session_type.value} is not in the calendar"
            ) from error

        try:
            # Telemetry is explicitly out of scope, and weather is unused.
            # Skipping both cuts the download by an order of magnitude.
            session.load(telemetry=False, weather=False, messages=True)
        except Exception as error:
            raise SessionNotAvailableError(
                f"timing data for {season} round {round_number} "
                f"{session_type.value} is not available yet"
            ) from error

        event = _event_from_row(season, session.event)
        warnings: list[str] = []

        laps = _optional_frame(session, "laps")
        drivers = self._require_classification(session, season, round_number, session_type)

        # Results key drivers by `DriverId` ("hamilton"), laps by abbreviation
        # ("HAM"). Reconciling here means everything downstream sees one
        # identity, instead of each consumer reinventing the mapping.
        aliases = self._alias_map(drivers)

        parsed_laps = tuple(self._laps(laps, aliases))
        if not parsed_laps:
            # Seasons before 2018 resolve through Ergast, which has the
            # classification but no timing. The session is real and worth
            # storing, but it is not complete, so it is not marked ingested and
            # a later re-ingest can fill it in if coverage improves.
            warnings.append("no lap data available for this session")

        return RawSession(
            event=event,
            session_type=session_type,
            session_date=to_datetime(getattr(session, "date", None)),
            drivers=drivers,
            results=tuple(self._results(session.results, session_type)),
            laps=parsed_laps,
            pit_stops=tuple(self._pit_stops(laps, aliases)),
            race_control=tuple(self._race_control(session)),
            is_partial=bool(warnings),
            warnings=tuple(warnings),
        )

    def _require_classification(
        self, session: Any, season: int, round_number: int, session_type: SessionType
    ) -> tuple[RawDriverEntry, ...]:
        """A session with no drivers has not happened yet.

        Separated from `fetch_session` so the "nothing here yet" path can be
        tested without a network call.
        """
        drivers = tuple(self._drivers(session.results))
        if not drivers:
            raise SessionNotAvailableError(
                f"{season} round {round_number} {session_type.value} has no classification yet"
            )
        return drivers

    # -- row mapping ---------------------------------------------------

    def _drivers(self, results: Any) -> list[RawDriverEntry]:
        if results is None or results.empty:
            return []
        entries: list[RawDriverEntry] = []
        for _, row in results.iterrows():
            driver_ref = to_str(row.get("DriverId"))
            full_name = to_str(row.get("FullName"))
            if driver_ref is None:
                # Without a stable reference the row cannot be keyed, and
                # guessing one would create duplicate drivers on re-ingest.
                continue
            entries.append(
                RawDriverEntry(
                    driver_ref=driver_ref,
                    code=to_str(row.get("Abbreviation")),
                    number=to_int(row.get("DriverNumber")),
                    first_name=to_str(row.get("FirstName")),
                    last_name=to_str(row.get("LastName")),
                    full_name=full_name or driver_ref,
                    nationality=to_str(row.get("CountryCode")),
                    constructor_ref=to_str(row.get("TeamId")),
                    constructor_name=to_str(row.get("TeamName")),
                )
            )
        return entries

    def _results(self, results: Any, session_type: SessionType) -> list[RawResult]:
        if results is None or results.empty:
            return []
        segments = session_type in SEGMENT_SESSIONS
        rows: list[RawResult] = []
        times: list[tuple[int | None, int | None, int | None]] = []
        for _, row in results.iterrows():
            driver_ref = to_str(row.get("DriverId"))
            if driver_ref is None:
                continue
            times.append(
                (to_int(row.get("Position")), to_int(row.get("Laps")), duration_ms(row.get("Time")))
            )
            rows.append(
                RawResult(
                    driver_ref=driver_ref,
                    position=to_int(row.get("Position")),
                    classified_position=to_str(row.get("ClassifiedPosition")),
                    grid_position=to_int(row.get("GridPosition")),
                    points=to_float(row.get("Points")),
                    status=to_str(row.get("Status")),
                    laps_completed=to_int(row.get("Laps")),
                    q1_time_ms=duration_ms(row.get("Q1")) if segments else None,
                    q2_time_ms=duration_ms(row.get("Q2")) if segments else None,
                    q3_time_ms=duration_ms(row.get("Q3")) if segments else None,
                )
            )
        if session_type not in TIMED_SESSIONS:
            return rows
        return [
            replace(result, gap_to_winner_ms=t.gap_to_winner_ms, race_time_ms=t.race_time_ms)
            for result, t in zip(rows, finishing_times(times), strict=True)
        ]

    def _laps(self, laps: Any, aliases: dict[str, str]) -> list[RawLap]:
        if laps is None or laps.empty:
            return []
        rows: list[RawLap] = []
        seen: set[tuple[str, int]] = set()
        for _, row in laps.iterrows():
            driver_ref = self._lap_driver_ref(row, aliases)
            lap_number = to_int(row.get("LapNumber"))
            if driver_ref is None or lap_number is None:
                continue
            # The unique constraint is (session, driver, lap). A duplicate in
            # the payload would abort the whole transaction, so drop it here.
            key = (driver_ref, lap_number)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                RawLap(
                    driver_ref=driver_ref,
                    lap_number=lap_number,
                    lap_time_ms=duration_ms(row.get("LapTime")),
                    sector_1_ms=duration_ms(row.get("Sector1Time")),
                    sector_2_ms=duration_ms(row.get("Sector2Time")),
                    sector_3_ms=duration_ms(row.get("Sector3Time")),
                    speed_trap_kph=to_float(row.get("SpeedST")),
                    position=to_int(row.get("Position")),
                    compound=to_compound(row.get("Compound")),
                    tyre_life=to_int(row.get("TyreLife")),
                    is_personal_best=to_bool(row.get("IsPersonalBest")),
                    track_status=to_str(row.get("TrackStatus")),
                    stint=to_int(row.get("Stint")),
                    is_deleted=bool(to_bool(row.get("Deleted"))),
                    is_accurate=to_bool(row.get("IsAccurate")) is not False,
                )
            )
        return rows

    @staticmethod
    def _alias_map(drivers: tuple[RawDriverEntry, ...]) -> dict[str, str]:
        """Every label a driver might appear under, mapped to `driver_ref`.

        Built from this session's own classification, so it is correct even
        when a code is reused by a different driver in another season.
        """
        aliases: dict[str, str] = {}
        for entry in drivers:
            aliases[entry.driver_ref] = entry.driver_ref
            if entry.code:
                aliases[entry.code] = entry.driver_ref
            if entry.number is not None:
                aliases[str(entry.number)] = entry.driver_ref
        return aliases

    @staticmethod
    def _lap_driver_ref(row: Any, aliases: dict[str, str]) -> str | None:
        """Resolve a lap row's driver to the canonical `driver_ref`.

        An unrecognised label returns None and the lap is dropped: attributing
        it to the wrong driver would be worse than losing it, and it would
        break the foreign key anyway.
        """
        for column in ("Driver", "DriverNumber"):
            label = to_str(row.get(column))
            if label is not None and label in aliases:
                return aliases[label]
        return None

    def _pit_stops(self, laps: Any, aliases: dict[str, str]) -> list[RawPitStop]:
        """Derived, because FastF1 exposes no pit-stop table.

        A stop spans two laps: `PitInTime` on the in-lap and `PitOutTime` on
        the following out-lap. The gap between them is the stationary time plus
        the pit lane transit.
        """
        if laps is None or laps.empty:
            return []

        stops: list[RawPitStop] = []
        for driver, driver_laps in laps.groupby("Driver", sort=False):
            driver_ref = aliases.get(to_str(driver) or "")
            if driver_ref is None:
                continue
            ordered = driver_laps.sort_values("LapNumber")
            rows = list(ordered.iterrows())
            stop_number = 0
            for index, (_, row) in enumerate(rows):
                pit_in = row.get("PitInTime")
                if duration_ms(pit_in) is None:
                    continue
                stop_number += 1
                duration = None
                if index + 1 < len(rows):
                    pit_out = rows[index + 1][1].get("PitOutTime")
                    in_ms, out_ms = duration_ms(pit_in), duration_ms(pit_out)
                    if in_ms is not None and out_ms is not None and out_ms > in_ms:
                        duration = out_ms - in_ms
                stops.append(
                    RawPitStop(
                        driver_ref=driver_ref,
                        stop_number=stop_number,
                        lap_number=to_int(row.get("LapNumber")),
                        duration_ms=duration,
                    )
                )
        return stops

    def _race_control(self, session: Any) -> list[RawRaceControlMessage]:
        messages = _optional_frame(session, "race_control_messages")
        if messages is None or messages.empty:
            return []
        rows: list[RawRaceControlMessage] = []
        for _, row in messages.iterrows():
            text = to_str(row.get("Message"))
            if text is None:
                continue
            rows.append(
                RawRaceControlMessage(
                    message=text,
                    timestamp=to_datetime(row.get("Time")),
                    lap_number=to_int(row.get("Lap")),
                    category=to_str(row.get("Category")),
                    flag=to_str(row.get("Flag")),
                    scope=to_str(row.get("Scope")),
                    driver_number=_racing_number(row, text),
                )
            )
        return rows
