"""Formatting shared by several wire models.

Kept apart from `race.py` so the report schema can use them without importing
the race schema, which itself refers to reports.
"""

from __future__ import annotations

import datetime as dt


def iso(value: dt.date | dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def race_id(season: int, round_number: int) -> str:
    """The identifier the frontend uses in URLs: `2024-14`."""
    return f"{season}-{round_number}"
