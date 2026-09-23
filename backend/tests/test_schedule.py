"""The season calendar: fetching it, caching it, and merging it with storage.

The calendar is the one thing the app shows before anything is ingested, so a
season nobody has asked about must still list every round. None of these tests
touch the network or the database.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import threading

import pytest

from app.analytics.race_stats import merge_calendar
from app.api.schemas.race import CalendarRound
from app.ingestion.base import ProviderError, RawEvent
from app.ingestion.schedule import FIRST_SEASON, ScheduleCache

TODAY = dt.date(2026, 9, 23)


def event(round_number: int, event_date: dt.date | None, **overrides: object) -> RawEvent:
    fields: dict[str, object] = {
        "season": 2026,
        "round_number": round_number,
        "event_name": f"Round {round_number} Grand Prix",
        "official_name": None,
        "event_date": event_date,
        "country": "Belgium",
        "location": "Spa-Francorchamps",
        "event_format": "conventional",
    }
    fields.update(overrides)
    return RawEvent(**fields)  # type: ignore[arg-type]


def stored(round_number: int, **overrides: object) -> CalendarRound:
    fields: dict[str, object] = {
        "season": 2026,
        "round": round_number,
        "event_name": f"Round {round_number} Grand Prix",
        "circuit_name": "Stored Circuit",
        "country": "Belgium",
        "event_date": "2026-03-08",
        "state": "ingested",
        "total_laps": 44,
    }
    fields.update(overrides)
    return CalendarRound(**fields)  # type: ignore[arg-type]


class ProviderDouble:
    """Counts schedule fetches; optionally fails or blocks."""

    def __init__(
        self,
        events: tuple[RawEvent, ...] = (),
        *,
        error: Exception | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.gate = gate
        self.calls: list[int] = []

    def fetch_schedule(self, season: int) -> tuple[RawEvent, ...]:
        self.calls.append(season)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.error is not None:
            raise self.error
        return self.events


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def cache(provider: ProviderDouble, clock: Clock | None = None) -> ScheduleCache:
    return ScheduleCache(
        provider,
        ttl=dt.timedelta(hours=12),
        clock=clock or Clock(),
        today=lambda: TODAY,
    )


# -- merging -----------------------------------------------------------


class TestMergeCalendar:
    def test_a_season_with_nothing_stored_lists_every_scheduled_round(self) -> None:
        schedule = (event(1, dt.date(2026, 3, 8)), event(2, dt.date(2026, 3, 15)))

        rounds = merge_calendar(schedule, [], today=TODAY)

        assert [r.round for r in rounds] == [1, 2]
        assert rounds[0].event_name == "Round 1 Grand Prix"
        assert rounds[0].circuit_name == "Spa-Francorchamps"
        assert rounds[0].country == "Belgium"
        assert rounds[0].event_date == "2026-03-08"
        assert rounds[0].total_laps is None

    def test_a_race_that_has_run_is_available(self) -> None:
        rounds = merge_calendar((event(1, dt.date(2026, 3, 8)),), [], today=TODAY)
        assert rounds[0].state == "available"

    def test_a_race_that_has_not_run_is_upcoming(self) -> None:
        rounds = merge_calendar((event(1, dt.date(2026, 12, 6)),), [], today=TODAY)
        assert rounds[0].state == "upcoming"

    def test_race_day_itself_is_available(self) -> None:
        # The race may be under way or just finished; opening it tries a fetch
        # and the provider says "not yet" if the data is not out.
        rounds = merge_calendar((event(1, TODAY),), [], today=TODAY)
        assert rounds[0].state == "available"

    def test_a_stored_round_keeps_what_the_database_says(self) -> None:
        schedule = (event(1, dt.date(2026, 3, 8)), event(2, dt.date(2026, 3, 15)))

        rounds = merge_calendar(schedule, [stored(1)], today=TODAY)

        assert rounds[0] == stored(1)
        assert rounds[1].state == "available"

    def test_a_stored_round_missing_from_the_schedule_is_not_dropped(self) -> None:
        # Storage is the truth for what we hold; a provider hiccup must not
        # make an ingested race vanish from the list.
        rounds = merge_calendar((event(1, dt.date(2026, 3, 8)),), [stored(5)], today=TODAY)
        assert [r.round for r in rounds] == [1, 5]

    def test_no_schedule_falls_back_to_storage(self) -> None:
        assert merge_calendar((), [stored(3), stored(1)], today=TODAY) == [stored(1), stored(3)]

    def test_a_missing_location_falls_back_to_the_event_name(self) -> None:
        rounds = merge_calendar((event(1, dt.date(2026, 3, 8), location=None),), [], today=TODAY)
        assert rounds[0].circuit_name == "Round 1 Grand Prix"


# -- fetching and caching ----------------------------------------------


@pytest.mark.asyncio
class TestScheduleCache:
    async def test_returns_the_provider_schedule(self) -> None:
        events = (event(1, dt.date(2026, 3, 8)),)
        assert await cache(ProviderDouble(events)).get(2026) == events

    async def test_a_repeat_request_is_served_from_memory(self) -> None:
        provider = ProviderDouble((event(1, dt.date(2026, 3, 8)),))
        schedules = cache(provider)

        await schedules.get(2026)
        await schedules.get(2026)

        assert provider.calls == [2026]

    async def test_seasons_are_cached_separately(self) -> None:
        provider = ProviderDouble((event(1, dt.date(2026, 3, 8)),))
        schedules = cache(provider)

        await schedules.get(2025)
        await schedules.get(2026)

        assert provider.calls == [2025, 2026]

    async def test_an_expired_entry_is_fetched_again(self) -> None:
        # A current season's calendar changes: races get cancelled or moved.
        clock = Clock()
        provider = ProviderDouble((event(1, dt.date(2026, 3, 8)),))
        schedules = cache(provider, clock)

        await schedules.get(2026)
        clock.now += dt.timedelta(hours=12, seconds=1).total_seconds()
        await schedules.get(2026)

        assert provider.calls == [2026, 2026]

    async def test_a_provider_failure_is_an_empty_schedule_not_an_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = ProviderDouble(error=ProviderError("upstream down"))

        assert await cache(provider).get(2026) == ()
        assert "upstream down" in caplog.text

    async def test_a_failure_is_not_cached(self) -> None:
        provider = ProviderDouble(error=ProviderError("upstream down"))
        schedules = cache(provider)

        await schedules.get(2026)
        provider.error = None
        provider.events = (event(1, dt.date(2026, 3, 8)),)

        assert len(await schedules.get(2026)) == 1

    @pytest.mark.parametrize("season", [FIRST_SEASON - 1, 1950, TODAY.year + 2, 9999])
    async def test_seasons_outside_the_supported_range_never_reach_upstream(
        self, season: int
    ) -> None:
        # The season is a path parameter anyone can set. It must not become a
        # way to make us hammer the provider with nonsense years.
        provider = ProviderDouble((event(1, dt.date(2026, 3, 8)),))

        assert await cache(provider).get(season) == ()
        assert provider.calls == []

    async def test_next_season_can_be_fetched(self) -> None:
        # The following year's calendar is published months in advance.
        provider = ProviderDouble((event(1, dt.date(2027, 3, 7)),))
        await cache(provider).get(TODAY.year + 1)
        assert provider.calls == [TODAY.year + 1]

    async def test_concurrent_requests_share_one_fetch(self) -> None:
        gate = threading.Event()
        provider = ProviderDouble((event(1, dt.date(2026, 3, 8)),), gate=gate)
        schedules = cache(provider)

        pending = asyncio.gather(schedules.get(2026), schedules.get(2026), schedules.get(2026))
        await asyncio.sleep(0.05)
        gate.set()
        results = await pending

        assert provider.calls == [2026]
        assert results[0] == results[1] == results[2]
