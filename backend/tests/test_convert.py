"""Conversions from pandas payloads to Python values.

These are exhaustive on purpose. Every case below corresponds to something
that actually occurs in FastF1 data, and each failure mode is quiet: a `NaN`
that becomes a huge integer, a `np.int64` psycopg cannot bind, a `""` that
reads as a real value. None of them raise at the point of the mistake.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.ingestion.convert import (
    duration_ms,
    is_missing,
    slugify,
    to_bool,
    to_date,
    to_datetime,
    to_float,
    to_int,
    to_str,
)


class TestIsMissing:
    @pytest.mark.parametrize(
        "value", [None, float("nan"), np.nan, pd.NaT, pd.NA, np.float64("nan")]
    )
    def test_recognises_every_flavour_of_missing(self, value: object) -> None:
        assert is_missing(value) is True

    @pytest.mark.parametrize("value", [0, 0.0, "", "x", False, pd.Timedelta(0)])
    def test_present_values_are_not_missing(self, value: object) -> None:
        # Zero and False are values, not absences. Treating them as missing
        # would drop a lap-one position or a legitimate zero.
        assert is_missing(value) is False


class TestToInt:
    def test_converts_numpy_integers(self) -> None:
        # psycopg cannot bind np.int64.
        result = to_int(np.int64(14))
        assert result == 14
        assert type(result) is int

    def test_nan_becomes_none_rather_than_a_nonsense_number(self) -> None:
        # int(float('nan')) raises; a careless guard yields garbage instead.
        assert to_int(float("nan")) is None

    @pytest.mark.parametrize("value", [None, pd.NaT, pd.NA, "", "abc"])
    def test_unusable_values_become_none(self, value: object) -> None:
        assert to_int(value) is None

    def test_floats_from_results_are_truncated(self) -> None:
        # FastF1 gives Position and GridPosition as floats.
        assert to_int(1.0) == 1
        assert to_int(np.float64(19.0)) == 19

    def test_infinity_is_not_an_integer(self) -> None:
        assert to_int(float("inf")) is None

    def test_numeric_strings_are_accepted(self) -> None:
        assert to_int("44") == 44


class TestToStr:
    def test_strips_whitespace(self) -> None:
        assert to_str("  Finished  ") == "Finished"

    @pytest.mark.parametrize("value", ["", "   ", None, pd.NaT])
    def test_empty_becomes_none(self, value: object) -> None:
        # Storing "" would make "has a status" true for a driver with none.
        assert to_str(value) is None

    def test_the_string_nan_is_kept(self) -> None:
        # A real string that happens to read "nan" is data, not a gap.
        assert to_str("nan") == "nan"


class TestToBool:
    def test_numpy_bool_becomes_python_bool(self) -> None:
        result = to_bool(np.bool_(True))
        assert result is True
        assert type(result) is bool

    def test_missing_stays_none_rather_than_false(self) -> None:
        # None means "unknown"; False means "measured, and negative".
        assert to_bool(None) is None
        assert to_bool(pd.NA) is None


class TestDurationMs:
    def test_converts_a_lap_time(self) -> None:
        assert duration_ms(pd.Timedelta(seconds=83.456)) == 83456

    def test_converts_a_plain_timedelta(self) -> None:
        assert duration_ms(dt.timedelta(minutes=1, seconds=23)) == 83000

    def test_nat_means_no_time_set(self) -> None:
        # Extremely common: an in-lap, an out-lap, a driver who never ran.
        assert duration_ms(pd.NaT) is None

    def test_rounds_to_the_nearest_millisecond(self) -> None:
        assert duration_ms(pd.Timedelta(seconds=83.4567)) == 83457

    def test_negative_durations_are_rejected(self) -> None:
        # Only ever corrupt data, and one negative lap time poisons every
        # average computed from the session.
        assert duration_ms(pd.Timedelta(seconds=-5)) is None

    def test_zero_is_a_value_not_a_gap(self) -> None:
        assert duration_ms(pd.Timedelta(0)) == 0

    def test_bare_seconds_are_accepted(self) -> None:
        assert duration_ms(83.456) == 83456


class TestToDatetime:
    def test_naive_timestamps_are_labelled_utc_not_shifted(self) -> None:
        # Shifting would move a session by the local offset and corrupt the
        # ordering of race control messages.
        result = to_datetime(pd.Timestamp("2024-07-28 13:00:00"))
        assert result == dt.datetime(2024, 7, 28, 13, 0, tzinfo=dt.UTC)

    def test_aware_timestamps_are_converted_to_utc(self) -> None:
        result = to_datetime(pd.Timestamp("2024-07-28 15:00:00+02:00"))
        assert result == dt.datetime(2024, 7, 28, 13, 0, tzinfo=dt.UTC)

    def test_every_result_is_timezone_aware(self) -> None:
        # The columns are TIMESTAMPTZ; a naive value would be read as server
        # local time.
        for value in (pd.Timestamp("2024-01-01"), dt.datetime(2024, 1, 1)):
            assert to_datetime(value).tzinfo is not None  # type: ignore[union-attr]

    def test_missing_becomes_none(self) -> None:
        assert to_datetime(pd.NaT) is None

    def test_a_date_is_extracted_from_a_timestamp(self) -> None:
        assert to_date(pd.Timestamp("2024-07-28 13:00:00")) == dt.date(2024, 7, 28)


class TestToFloat:
    def test_numpy_float(self) -> None:
        assert to_float(np.float64(321.5)) == 321.5

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), pd.NaT, None])
    def test_unusable_values_become_none(self, value: object) -> None:
        assert to_float(value) is None


class TestSlugify:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Spa-Francorchamps", "spa-francorchamps"),
            ("Autodromo Nazionale Monza", "autodromo-nazionale-monza"),
            ("Yas Marina Circuit", "yas-marina-circuit"),
            ("  Sakhir  ", "sakhir"),
            ("São Paulo", "sao-paulo"),
        ],
    )
    def test_produces_a_stable_key(self, value: str, expected: str) -> None:
        # Stability is what makes re-ingestion idempotent: the same circuit
        # must produce the same key every time.
        assert slugify(value) == expected

    def test_is_deterministic(self) -> None:
        assert slugify("Circuit de Monaco") == slugify("Circuit de Monaco")

    @pytest.mark.parametrize("value", [None, "", "   ", "---"])
    def test_unusable_input_becomes_none(self, value: object) -> None:
        assert slugify(value) is None
