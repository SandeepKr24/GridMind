"""The published season calendar, cached in memory.

The race list must show every round of a season before any of it is ingested,
so the calendar comes from the provider rather than from storage. Fetching it
is cheap (under a second, and FastF1 caches it on disk) but still blocking
pandas work, so it runs in a worker thread and each season is held in memory
for a while.

A failure here must never break the page: the caller falls back to the rounds
it has stored, which is a truthful if shorter answer.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable
from typing import Protocol

from app.ingestion.base import ProviderError, RawEvent

logger = logging.getLogger(__name__)

#: FastF1's timing coverage starts in 2018; the frontend's season picker agrees.
FIRST_SEASON = 2018


class ScheduleProvider(Protocol):
    def fetch_schedule(self, season: int) -> tuple[RawEvent, ...]: ...


class ScheduleSource(Protocol):
    """What the routes need: a season's calendar, possibly empty."""

    async def get(self, season: int) -> tuple[RawEvent, ...]: ...


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class ScheduleCache:
    def __init__(
        self,
        provider: ScheduleProvider,
        *,
        ttl: dt.timedelta,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], dt.date] = _utc_today,
    ) -> None:
        self._provider = provider
        self._ttl_seconds = ttl.total_seconds()
        self._clock = clock
        self._today = today
        self._entries: dict[int, tuple[float, tuple[RawEvent, ...]]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _in_range(self, season: int) -> bool:
        # Next year's calendar is published months ahead. Anything else is a
        # user-supplied year we have no reason to ask upstream about.
        return FIRST_SEASON <= season <= self._today().year + 1

    def _fresh(self, season: int) -> tuple[RawEvent, ...] | None:
        entry = self._entries.get(season)
        if entry is None or self._clock() - entry[0] > self._ttl_seconds:
            return None
        return entry[1]

    async def get(self, season: int) -> tuple[RawEvent, ...]:
        """The season's rounds, or an empty tuple if they cannot be had."""
        if not self._in_range(season):
            return ()
        cached = self._fresh(season)
        if cached is not None:
            return cached

        # One fetch per season at a time: a burst of page loads on a cold
        # cache should cost one upstream request, not one each.
        lock = self._locks.setdefault(season, asyncio.Lock())
        async with lock:
            cached = self._fresh(season)
            if cached is not None:
                return cached
            try:
                events = await asyncio.to_thread(self._provider.fetch_schedule, season)
            except ProviderError as error:
                # Not cached, so the next request retries.
                logger.warning("calendar for %s unavailable: %s", season, error)
                return ()
            self._entries[season] = (self._clock(), events)
            return events
