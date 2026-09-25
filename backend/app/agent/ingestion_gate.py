"""Decide whether a question can be answered from stored data, and at what cost.

The gate is what keeps on-demand ingestion cheap. The model never triggers a
fetch: it proposes entities, and this ordinary Python decides.

- Standings and unsupported questions need no session data: pass through.
- A season-wide question would need every race of a season: refused, with a
  suggestion to ask about standings or one race instead.
- More sessions than the per-question budget: refused.
- A session that has not run yet: refused, rather than a fetch that must fail.
- Every session already stored: ready, with no upstream request at all.
- Otherwise every missing session is submitted to the job runner at once,
  and the first unfinished job id goes back to the client.

One known gap: a session stored between the gate's check and its submit gets
a `skipped_cached` job row from the runner. Harmless, and the runner's own
documented behaviour for that race.

The chat contract carries one job id. The frontend shows the Loading Pit for
it and asks the same question again once it succeeds; if a second session is
still fetching then, the gate returns that job's id. Locking, de-duplication
of concurrent requests, the concurrency cap and failure messages all belong
to the job runner; `IngestBusyError` propagates for the API to turn into 503.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.entity_resolver import WHICH_RACE
from app.db.models.enums import SessionType
from app.ingestion.jobs import JobKey
from app.ingestion.runner import IngestBusyError, Submission
from app.ingestion.schedule import session_has_started

logger = logging.getLogger(__name__)


class GateStatus(StrEnum):
    #: Everything needed is stored (or nothing is needed). Answer now.
    READY = "ready"
    #: Fetches are running. Return `job_id` to the client and stop.
    INGESTING = "ingesting"
    #: The question cannot be answered this way. Show `message`.
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: GateStatus
    job_id: str | None = None
    #: Sessions still being fetched when the status is INGESTING.
    waiting_on: tuple[ResolvedSession, ...] = ()
    message: str | None = None


class SessionRunner(Protocol):
    async def is_ingested(self, key: JobKey) -> bool: ...
    async def submit(self, key: JobKey) -> Submission: ...


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def _key(session: ResolvedSession) -> JobKey:
    return JobKey(session.year, session.round_number, session.session_type)


def season_refusal(year: int | None) -> str:
    season = f"the {year} season" if year is not None else "a whole season"
    example = year if year is not None else "2024"
    return (
        f"That needs every race of {season}, and I fetch race data one session at a "
        f"time. Ask about the {example} championship standings, or about one race, "
        f'such as "the {example} British Grand Prix".'
    )


def not_run_refusal(session: ResolvedSession) -> str:
    message = f"The {session.describe()} hasn't run yet"
    day = session.event_date
    if day is not None and session.session_type is SessionType.RACE:
        # Built by hand: "%-d" (no leading zero) does not exist on Windows.
        message += f"; it is scheduled for {day.day} {day:%B %Y}"
    return message + "."


class IngestionGate:
    def __init__(
        self,
        runner: SessionRunner,
        *,
        max_sessions: int,
        today: Callable[[], dt.date] = _utc_today,
    ) -> None:
        self._runner = runner
        self._max_sessions = max_sessions
        self._today = today

    async def check(self, entities: ResolvedEntities) -> GateDecision:
        decision = await self._decide(entities)
        logger.info(
            "gate intent=%s sessions=%s decision=%s job=%s",
            entities.intent.value,
            [s.describe() for s in entities.sessions],
            decision.status.value,
            decision.job_id,
        )
        return decision

    async def _decide(self, entities: ResolvedEntities) -> GateDecision:
        if entities.intent is Intent.SEASON:
            return _refuse(season_refusal(entities.year))
        if entities.intent is not Intent.SESSION:
            return GateDecision(GateStatus.READY)
        sessions = entities.sessions
        if not sessions:
            # The resolver asks instead of producing this; never answer a
            # session question with no session behind it.
            return _refuse(WHICH_RACE)

        if len(sessions) > self._max_sessions:
            return _refuse(
                f"That question covers {len(sessions)} sessions, and I can look at up to "
                f"{self._max_sessions} per question. Try asking about fewer races or sessions."
            )

        today = self._today()
        for session in sessions:
            if not session_has_started(session.event_date, session.session_type, today):
                return _refuse(not_run_refusal(session))

        missing = [s for s in sessions if not await self._runner.is_ingested(_key(s))]
        if not missing:
            return GateDecision(GateStatus.READY)

        # Submit every missing session now so they fetch in parallel, even
        # though the client can only follow one job id at a time.
        job_ids: list[str] = []
        for s in missing:
            try:
                job_ids.append((await self._runner.submit(_key(s))).job_id)
            except IngestBusyError:
                if not job_ids:
                    raise
                # Follow the fetch that did start; asking again later queues
                # the rest once there is room.
                break
        return GateDecision(GateStatus.INGESTING, job_id=job_ids[0], waiting_on=tuple(missing))


def _refuse(message: str) -> GateDecision:
    return GateDecision(GateStatus.REFUSED, message=message)
