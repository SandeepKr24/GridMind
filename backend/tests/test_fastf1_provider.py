"""Mapping FastF1's frames onto our value objects.

Built from stub DataFrames shaped like the real ones, so the suite stays
offline and fast. The column names and dtypes here were taken from an actual
2024 session, not invented.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app.db.models.enums import SessionType
from app.ingestion.base import ProviderError, RawDriverEntry, SessionNotAvailableError
from app.ingestion.fastf1_provider import (
    SESSION_IDENTIFIERS,
    FastF1Provider,
    _optional_frame,
    _session_types_for,
    car_in_message,
)

PROVIDER = FastF1Provider(".fastf1-cache")


def results_frame(**overrides: Any) -> pd.DataFrame:
    row: dict[str, Any] = {
        "DriverId": "hamilton",
        "Abbreviation": "HAM",
        "DriverNumber": "44",
        "FirstName": "Lewis",
        "LastName": "Hamilton",
        "FullName": "Lewis Hamilton",
        "CountryCode": "GBR",
        "TeamId": "mercedes",
        "TeamName": "Mercedes",
        "Position": 1.0,
        "ClassifiedPosition": "1",
        "GridPosition": 3.0,
        "Points": 25.0,
        "Status": "Finished",
        "Laps": 44.0,
        "Q1": pd.NaT,
        "Q2": pd.NaT,
        "Q3": pd.NaT,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def laps_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    base: dict[str, Any] = {
        "Driver": "HAM",
        "DriverNumber": "44",
        "LapNumber": 1.0,
        "LapTime": pd.Timedelta(seconds=83),
        "Sector1Time": pd.NaT,
        "Sector2Time": pd.NaT,
        "Sector3Time": pd.NaT,
        "SpeedST": 309.0,
        "Position": 2.0,
        "Compound": "MEDIUM",
        "TyreLife": 1.0,
        "IsPersonalBest": False,
        "TrackStatus": "1",
        "Stint": 1.0,
        "Deleted": False,
        "IsAccurate": True,
        "PitInTime": pd.NaT,
        "PitOutTime": pd.NaT,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


HAMILTON = RawDriverEntry(
    driver_ref="hamilton",
    code="HAM",
    number=44,
    first_name="Lewis",
    last_name="Hamilton",
    full_name="Lewis Hamilton",
    nationality="GBR",
    constructor_ref="mercedes",
    constructor_name="Mercedes",
)
ALIASES = FastF1Provider._alias_map((HAMILTON,))


class TestSessionIdentifiers:
    def test_every_session_type_can_be_requested(self) -> None:
        # A missing entry raises KeyError deep inside fetch_session.
        assert set(SESSION_IDENTIFIERS) == set(SessionType)

    def test_identifiers_are_the_ones_fastf1_accepts(self) -> None:
        assert SESSION_IDENTIFIERS[SessionType.RACE] == "R"
        assert SESSION_IDENTIFIERS[SessionType.SPRINT_QUALIFYING] == "SQ"
        assert SESSION_IDENTIFIERS[SessionType.PRACTICE_3] == "FP3"


class TestWeekendFormats:
    def test_conventional_weekend(self) -> None:
        row = pd.Series(
            {
                "Session1": "Practice 1",
                "Session2": "Practice 2",
                "Session3": "Practice 3",
                "Session4": "Qualifying",
                "Session5": "Race",
            }
        )
        assert _session_types_for(row) == (
            SessionType.PRACTICE_1,
            SessionType.PRACTICE_2,
            SessionType.PRACTICE_3,
            SessionType.QUALIFYING,
            SessionType.RACE,
        )

    def test_sprint_weekend_has_no_practice_2_or_3(self) -> None:
        row = pd.Series(
            {
                "Session1": "Practice 1",
                "Session2": "Sprint Qualifying",
                "Session3": "Sprint",
                "Session4": "Qualifying",
                "Session5": "Race",
            }
        )
        types = _session_types_for(row)
        assert SessionType.SPRINT in types
        assert SessionType.PRACTICE_2 not in types

    def test_the_older_sprint_shootout_name_is_understood(self) -> None:
        # Renamed to "Sprint Qualifying" in 2024; 2023 data still says this.
        row = pd.Series({"Session1": "Sprint Shootout", "Session5": "Race"})
        assert SessionType.SPRINT_QUALIFYING in _session_types_for(row)

    def test_race_is_always_present(self) -> None:
        assert SessionType.RACE in _session_types_for(pd.Series({}))


class TestDrivers:
    def test_maps_a_classification_row(self) -> None:
        driver = PROVIDER._drivers(results_frame())[0]
        assert driver.driver_ref == "hamilton"
        assert driver.code == "HAM"
        assert driver.number == 44
        assert driver.constructor_ref == "mercedes"

    def test_a_row_without_a_stable_reference_is_dropped(self) -> None:
        # Inventing a ref would create a duplicate driver on the next ingest.
        assert PROVIDER._drivers(results_frame(DriverId=None)) == []

    def test_empty_results_give_no_drivers(self) -> None:
        assert PROVIDER._drivers(pd.DataFrame()) == []


class TestResults:
    def test_race_results_carry_no_segment_times(self) -> None:
        result = PROVIDER._results(results_frame(), SessionType.RACE)[0]
        assert (result.q1_time_ms, result.q2_time_ms, result.q3_time_ms) == (None, None, None)

    def test_qualifying_results_carry_segment_times(self) -> None:
        frame = results_frame(
            Q1=pd.Timedelta(seconds=114.938), Q2=pd.Timedelta(seconds=113.837), Q3=pd.NaT
        )
        result = PROVIDER._results(frame, SessionType.QUALIFYING)[0]
        assert result.q1_time_ms == 114938
        assert result.q2_time_ms == 113837
        # Eliminated in Q2: no Q3 time, and that must stay null rather than 0.
        assert result.q3_time_ms is None

    def test_float_positions_become_integers(self) -> None:
        result = PROVIDER._results(results_frame(), SessionType.RACE)[0]
        assert result.position == 1
        assert result.grid_position == 3


class TestAliasResolution:
    def test_results_and_laps_end_up_with_the_same_identity(self) -> None:
        # Results say "hamilton", laps say "HAM". Downstream must see one.
        laps = PROVIDER._laps(laps_frame([{}]), ALIASES)
        assert laps[0].driver_ref == "hamilton"

    def test_a_driver_number_also_resolves(self) -> None:
        laps = PROVIDER._laps(laps_frame([{"Driver": None}]), ALIASES)
        assert laps[0].driver_ref == "hamilton"

    def test_an_unknown_driver_is_dropped_not_guessed(self) -> None:
        # Attributing a lap to the wrong driver is worse than losing it, and
        # it would violate the foreign key regardless.
        assert PROVIDER._laps(laps_frame([{"Driver": "ZZZ", "DriverNumber": "99"}]), ALIASES) == []


class TestLaps:
    def test_maps_a_lap(self) -> None:
        lap = PROVIDER._laps(laps_frame([{}]), ALIASES)[0]
        assert lap.lap_number == 1
        assert lap.lap_time_ms == 83000
        assert lap.compound == "MEDIUM"
        assert lap.track_status == "1"

    @pytest.mark.parametrize("placeholder", ["None", "UNKNOWN", "TEST_UNKNOWN", "nan", ""])
    def test_a_placeholder_compound_is_stored_as_null(self, placeholder: str) -> None:
        # Seen in stored data: 25 laps with compound 'None', the string.
        lap = PROVIDER._laps(laps_frame([{"Compound": placeholder}]), ALIASES)[0]
        assert lap.compound is None

    def test_a_compound_is_stored_in_upper_case(self) -> None:
        lap = PROVIDER._laps(laps_frame([{"Compound": "Intermediate"}]), ALIASES)[0]
        assert lap.compound == "INTERMEDIATE"

    def test_a_lap_with_no_time_keeps_a_null_not_a_zero(self) -> None:
        # In-laps and out-laps have no representative time. Zero would drag
        # every average down.
        lap = PROVIDER._laps(laps_frame([{"LapTime": pd.NaT}]), ALIASES)[0]
        assert lap.lap_time_ms is None

    def test_duplicate_laps_are_dropped(self) -> None:
        # (session, driver, lap) is unique. A duplicate in the payload would
        # abort the entire ingestion transaction.
        laps = PROVIDER._laps(laps_frame([{"LapNumber": 1.0}, {"LapNumber": 1.0}]), ALIASES)
        assert len(laps) == 1

    def test_a_lap_without_a_number_is_dropped(self) -> None:
        assert PROVIDER._laps(laps_frame([{"LapNumber": pd.NaT}]), ALIASES) == []

    def test_deleted_and_inaccurate_flags_survive(self) -> None:
        lap = PROVIDER._laps(laps_frame([{"Deleted": True, "IsAccurate": False}]), ALIASES)[0]
        assert lap.is_deleted is True
        assert lap.is_accurate is False


class TestPitStops:
    """Derived from lap data, because FastF1 exposes no pit-stop table."""

    def test_a_stop_spans_the_in_lap_and_the_out_lap(self) -> None:
        frame = laps_frame(
            [
                {"LapNumber": 10.0},
                {"LapNumber": 11.0, "PitInTime": pd.Timedelta(seconds=1000)},
                {"LapNumber": 12.0, "PitOutTime": pd.Timedelta(seconds=1023.198)},
            ]
        )
        stops = PROVIDER._pit_stops(frame, ALIASES)
        assert len(stops) == 1
        assert stops[0].lap_number == 11
        assert stops[0].stop_number == 1
        assert stops[0].duration_ms == 23198

    def test_stops_are_numbered_in_order(self) -> None:
        frame = laps_frame(
            [
                {"LapNumber": 5.0, "PitInTime": pd.Timedelta(seconds=500)},
                {"LapNumber": 6.0, "PitOutTime": pd.Timedelta(seconds=520)},
                {"LapNumber": 25.0, "PitInTime": pd.Timedelta(seconds=2000)},
                {"LapNumber": 26.0, "PitOutTime": pd.Timedelta(seconds=2022)},
            ]
        )
        stops = PROVIDER._pit_stops(frame, ALIASES)
        assert [s.stop_number for s in stops] == [1, 2]
        assert [s.lap_number for s in stops] == [5, 25]

    def test_a_stop_on_the_final_lap_has_no_duration(self) -> None:
        # The car retired or the session ended; there is no out-lap to measure
        # against. Recording the stop with a null beats inventing a number.
        frame = laps_frame([{"LapNumber": 44.0, "PitInTime": pd.Timedelta(seconds=3000)}])
        stops = PROVIDER._pit_stops(frame, ALIASES)
        assert len(stops) == 1
        assert stops[0].duration_ms is None

    def test_a_session_with_no_stops_yields_none(self) -> None:
        assert PROVIDER._pit_stops(laps_frame([{}]), ALIASES) == []

    def test_empty_laps_are_handled(self) -> None:
        assert PROVIDER._pit_stops(pd.DataFrame(), ALIASES) == []


class TestRaceControl:
    def test_maps_a_message(self) -> None:
        class FakeSession:
            race_control_messages = pd.DataFrame(
                [
                    {
                        "Time": pd.Timestamp("2024-07-28 12:20:01"),
                        "Category": "Flag",
                        "Message": "GREEN LIGHT - PIT EXIT OPEN",
                        "Flag": "GREEN",
                        "Scope": "Track",
                        "RacingNumber": None,
                        "Lap": 1,
                    }
                ]
            )

        message = PROVIDER._race_control(FakeSession())[0]
        assert message.message == "GREEN LIGHT - PIT EXIT OPEN"
        assert message.flag == "GREEN"
        assert message.timestamp is not None
        assert message.timestamp.tzinfo is not None
        # Session-wide events have no driver.
        assert message.driver_number is None

    @pytest.mark.parametrize(
        ("message", "car"),
        [
            ("CAR 4 (NOR) TIME 1:50.504 DELETED - TRACK LIMITS AT TURN 6 LAP 2 15:06:24", 4),
            ("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) - SPEEDING", 55),
            ("TURN 5 INCIDENT INVOLVING CARS 23 (ALB) AND 4 (NOR) NOTED", None),
            ("CAR 44 (HAM) AND CAR 1 (VER) COLLISION NOTED", None),
            ("CAR 4 (NOR) TIME DELETED - CAR 4 (NOR) WARNED", 4),
            ("SAFETY CAR DEPLOYED", None),
            ("RISK OF RAIN FOR F1 RACE IS 0 %", None),
        ],
    )
    def test_a_single_car_named_in_the_message_is_attributed(
        self, message: str, car: int | None
    ) -> None:
        assert car_in_message(message) == car

    def test_racing_number_wins_over_the_message(self) -> None:
        class FakeSession:
            race_control_messages = pd.DataFrame(
                [{"Message": "CAR 4 (NOR) TIME DELETED", "RacingNumber": "16", "Lap": 3}]
            )

        assert PROVIDER._race_control(FakeSession())[0].driver_number == 16

    def test_a_message_naming_a_car_gets_its_number(self) -> None:
        class FakeSession:
            race_control_messages = pd.DataFrame(
                [{"Message": "CAR 4 (NOR) TIME DELETED", "RacingNumber": None, "Lap": 3}]
            )

        assert PROVIDER._race_control(FakeSession())[0].driver_number == 4

    def test_a_session_without_messages_is_not_an_error(self) -> None:
        class NoMessages:
            race_control_messages = None

        assert PROVIDER._race_control(NoMessages()) == []


class TestPartiallyLoadedSessions:
    """Seasons before 2018 resolve through Ergast: classification, no timing."""

    def test_an_unloaded_frame_reads_as_none_not_an_exception(self) -> None:
        # FastF1 raises DataNotLoadedError on `session.laps` for these, rather
        # than returning an empty frame. Unguarded, one attribute access fails
        # an ingest whose results we could have stored.
        class PartiallyLoaded:
            @property
            def laps(self) -> Any:
                raise RuntimeError("DataNotLoadedError")

        assert _optional_frame(PartiallyLoaded(), "laps") is None

    def test_a_present_frame_is_returned_unchanged(self) -> None:
        frame = laps_frame([{}])

        class Loaded:
            laps = frame

        assert _optional_frame(Loaded(), "laps") is frame

    def test_laps_handles_a_missing_frame(self) -> None:
        assert PROVIDER._laps(None, ALIASES) == []

    def test_pit_stops_handle_a_missing_frame(self) -> None:
        assert PROVIDER._pit_stops(None, ALIASES) == []


class TestFailures:
    def test_a_session_with_no_classification_is_unavailable(self) -> None:
        # Not a crash. A future race, or one that finished minutes ago, is
        # expected to have nothing yet, and the UI says "not available yet"
        # rather than showing a failure.
        class Empty:
            results = pd.DataFrame()
            laps = pd.DataFrame()
            race_control_messages = None
            event = pd.Series({"RoundNumber": 1, "EventName": "Test GP"})
            date = None

            def load(self, **_: Any) -> None:
                return None

        provider = FastF1Provider(".fastf1-cache")
        with pytest.raises(SessionNotAvailableError):
            # Reach past the network by handing fetch_session its session.
            provider._require_classification(Empty(), 2030, 1, SessionType.RACE)


class TestScheduleFailures:
    @pytest.fixture
    def schedule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import fastf1

        frame = pd.DataFrame([{"RoundNumber": 1, "EventName": "Test GP", "EventDate": None}])
        monkeypatch.setattr(fastf1, "get_event_schedule", lambda *_, **__: frame)
        monkeypatch.setattr("app.ingestion.fastf1_provider.enable_cache", lambda _: None)

    @pytest.mark.usefixtures("schedule")
    def test_a_row_that_cannot_be_read_is_a_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The calendar route degrades on ProviderError. Anything else escaping
        # from row parsing would turn one odd row into a 500 for the season.
        def broken(*_: Any) -> None:
            raise ValueError("unexpected column shape")

        monkeypatch.setattr("app.ingestion.fastf1_provider._event_from_row", broken)
        with pytest.raises(ProviderError, match="unexpected column shape"):
            PROVIDER.fetch_schedule(2030)

    @pytest.mark.usefixtures("schedule")
    def test_a_readable_schedule_still_parses(self) -> None:
        events = PROVIDER.fetch_schedule(2030)
        assert [(e.round_number, e.event_name) for e in events] == [(1, "Test GP")]
