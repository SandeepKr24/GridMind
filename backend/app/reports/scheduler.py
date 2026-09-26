"""Write a report for each race soon after it finishes, without being asked.

Every few hours the scheduler looks at the season's calendar for races run in
the last few days. For each one without a report it starts a report job,
marked `automatic`; the job fetches the race and writes it up exactly as an
on-request report would.

Cheap by design:
- Outside a race's window, a check reads only the calendar, which is cached
  in memory. It touches neither the database nor the provider, so it does not
  wake Neon's suspended compute on the days nothing is happening.
- A race whose results are not published yet fails at the fetch, before any
  LLM call, and is simply tried again at the next check.
- Historic races are never touched: they get reports only when asked.

An in-process loop rather than APScheduler: one periodic task needs no
scheduler library, and it stops with the app.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.db.models.enums import JobStage, JobStatus, ReportTrigger
from app.ingestion.base import RawEvent
from app.ingestion.jobs import JobRecord
from app.ingestion.schedule import ScheduleSource
from app.reports.jobs import ReportBusyError

logger = logging.getLogger(__name__)

#: Give the app time to start before the first check.
FIRST_CHECK_DELAY_SECONDS = 60.0


#: Failures in the writing stage before a race is left for someone to request.
MAX_WRITE_FAILURES = 2


class ReportStarter(Protocol):
    async def submit(self, season: int, round_number: int, trigger: ReportTrigger = ...) -> str: ...
    def get(self, job_id: str) -> JobRecord | None: ...


class ReportLookup(Protocol):
    async def exists(self, season: int, round_number: int) -> bool: ...


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


class AutoReporter:
    def __init__(
        self,
        calendar: ScheduleSource,
        reports: ReportStarter,
        archive: ReportLookup,
        *,
        window_days: int,
        today: Callable[[], dt.date] = _utc_today,
    ) -> None:
        self._calendar = calendar
        self._reports = reports
        self._archive = archive
        self._window = dt.timedelta(days=window_days)
        self._today = today
        # In memory: a restart forgets them, which costs at most one more try.
        self._last_job: dict[tuple[int, int], str] = {}
        self._write_failures: dict[tuple[int, int], int] = {}

    async def recent_races(self) -> list[RawEvent]:
        """Races run from `window_days` ago up to yesterday, oldest first.

        Today's race is left out: it has no results until hours after the
        flag, and tomorrow's first check picks it up.
        """
        today = self._today()
        earliest = today - self._window
        seasons = sorted({earliest.year, today.year})
        events = [e for season in seasons for e in await self._calendar.get(season)]
        recent = [
            e for e in events if e.event_date is not None and earliest <= e.event_date < today
        ]
        return sorted(recent, key=lambda e: (e.event_date or dt.date.min, e.round_number))

    def _gave_up_on(self, race: tuple[int, int]) -> bool:
        """Count the last job's outcome; True once writing has failed too often.

        A job that failed before the writing stage (results not published,
        incomplete data) cost no tokens, and retrying it is the point. One that
        failed while writing spent a report's worth of tokens, and a model that
        keeps failing its checks will likely keep failing.
        """
        job_id = self._last_job.pop(race, None)
        record = self._reports.get(job_id) if job_id else None
        failed_writing = (
            record is not None
            and record.status is JobStatus.FAILED
            and record.stage is JobStage.ANSWERING
        )
        if failed_writing:
            self._write_failures[race] = self._write_failures.get(race, 0) + 1
        return self._write_failures.get(race, 0) >= MAX_WRITE_FAILURES

    async def check_once(self) -> list[str]:
        """Start a report for each recent race that has none. Returns the job ids."""
        started: list[str] = []
        for event in await self.recent_races():
            race = (event.season, event.round_number)
            if self._gave_up_on(race):
                continue
            if await self._archive.exists(event.season, event.round_number):
                continue
            try:
                job_id = await self._reports.submit(
                    event.season, event.round_number, ReportTrigger.AUTOMATIC
                )
            except ReportBusyError:
                logger.info("auto report: queue full, will retry %s", event.event_name)
                continue
            logger.info("auto report: started %s %s (%s)", event.season, event.event_name, job_id)
            self._last_job[race] = job_id
            started.append(job_id)
        return started

    async def run(
        self,
        interval: dt.timedelta,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        first_delay: float = FIRST_CHECK_DELAY_SECONDS,
    ) -> None:
        """Check forever. A failed check is logged and the loop carries on."""
        await sleep(first_delay)
        while True:
            try:
                await self.check_once()
            except Exception:
                logger.exception("auto report: check failed; retrying at the next interval")
            await sleep(interval.total_seconds())
