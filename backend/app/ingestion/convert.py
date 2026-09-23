"""Pandas-to-Python conversions for provider payloads.

Isolated from the provider because this is where timing ingestion usually goes
wrong, and because these are pure functions that can be tested exhaustively
without touching the network.

Three traps, all of which appear in real FastF1 data:

* **Missing values wear several costumes.** `NaT`, `NaN`, `None` and `pd.NA`
  all mean "no value", and `NaN` is a float, so a naive `int(value)` yields
  a nonsense number instead of raising.
* **numpy scalars are not Python scalars.** `np.int64` reaches psycopg as an
  unknown type; `np.bool_` is not `bool`.
* **`NaN != NaN`.** Any equality-based check for missing data silently fails.
"""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from typing import Any

import pandas as pd


def is_missing(value: Any) -> bool:
    """True for every shape a missing value takes.

    `pd.isna` returns an array for list-likes, which is not a truth value, so
    those are treated as present and handled by the caller.
    """
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool | pd.BooleanDtype) else result is True


def to_int(value: Any) -> int | None:
    """A Python int, or None.

    Guards against `int(float('nan'))`, which raises, and against `np.int64`,
    which psycopg does not recognise.
    """
    if is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(number)


def to_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def to_str(value: Any) -> str | None:
    """A non-empty stripped string, or None.

    Empty and whitespace-only strings become None: storing `""` would make
    "has a value" true for something that has none.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def to_bool(value: Any) -> bool | None:
    """A Python bool, or None. `np.bool_` is not `bool`."""
    if is_missing(value):
        return None
    return bool(value)


def duration_ms(value: Any) -> int | None:
    """A Timedelta as whole milliseconds.

    Lap and sector times arrive as `pd.Timedelta`, or `NaT` when the driver set
    no time. Negative values are rejected: they only arise from corrupt data,
    and a negative lap time would poison every average built on it.
    """
    if is_missing(value):
        return None
    if isinstance(value, pd.Timedelta | dt.timedelta):
        total = value.total_seconds()
    else:
        number = to_float(value)
        if number is None:
            return None
        total = number
    if total < 0:
        return None
    return round(total * 1000)


def to_datetime(value: Any) -> dt.datetime | None:
    """A timezone-aware UTC datetime, or None.

    FastF1 mixes naive and tz-aware timestamps depending on the field. Naive
    ones are session-local wall clock already normalised to UTC upstream, so
    they are labelled UTC rather than shifted.
    """
    if is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        stamp = value.to_pydatetime()
    elif isinstance(value, dt.datetime):
        stamp = value
    else:
        return None
    if stamp.tzinfo is None:
        return dt.datetime(
            stamp.year,
            stamp.month,
            stamp.day,
            stamp.hour,
            stamp.minute,
            stamp.second,
            stamp.microsecond,
            tzinfo=dt.UTC,
        )
    converted: dt.datetime = stamp.astimezone(dt.UTC)
    return converted


def to_date(value: Any) -> dt.date | None:
    stamp = to_datetime(value)
    return stamp.date() if stamp else None


def slugify(value: Any) -> str | None:
    """A stable lowercase identifier.

    Used for circuits, where the provider gives a display name but no stable
    key. Keeping it deterministic is what makes re-ingestion idempotent.

    Accents are folded to ASCII, so "São Paulo" becomes "sao-paulo". Without
    that, `str.isalnum()` keeps `ã` — it is alphanumeric in Unicode — and the
    key would depend on how the provider happened to spell the venue.
    """
    text = to_str(value)
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in decomposed if not unicodedata.combining(char))
    slug = "".join(char.lower() if char.isascii() and char.isalnum() else "-" for char in text)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or None
