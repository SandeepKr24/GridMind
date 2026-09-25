"""The ingestion job runner: on-demand session fetches as background jobs.

A cold fetch takes 30-120 seconds, far too long to hold an HTTP request open,
so a request only *submits* a job and gets its id back; the Loading Pit then
polls the job row, which this runner advances stage by stage.

Guarantees, and where each one lives:

* **One job per session.** The partial unique index on `ingestion_jobs`
  (see `jobs.claim`). Within this process an asyncio lock also serialises
  submissions, so a request never mistakes a job being created for an orphan.
* **Bounded.** At most `max_concurrent` fetches run at once; beyond that jobs
  wait as `pending`, and beyond `max_pending` new sessions are refused.
* **Timeout-guarded.** A job past `timeout_seconds` is failed and its slot freed.
  The fetch thread itself cannot be killed and finishes in the background; its
  result is discarded.
* **Never stuck.** This assumes one backend process, which is how it is deployed.
  A live job row this process does not own was therefore left by a restart, and
  is failed as interrupted the next time anyone polls it or asks for its session.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from app.db.database import Database
from app.db.models.enums import JobStage, JobStatus, SessionType
from app.ingestion import jobs
from app.ingestion.base import ProviderError, RawSession, SessionNotAvailableError
from app.ingestion.jobs import JobKey, JobRecord
from app.ingestion.normalizer import SessionWriter, StoredSession

logger = logging.getLogger(__name__)

INTERRUPTED = "Interrupted: the server restarted before this fetch finished. Try again."
PROVIDER_FAILED = "Could not fetch the timing data from the provider. Try again in a few minutes."
UNEXPECTED = "Something went wrong while storing this session. Try again."
INCOMPLETE = (
    "The timing data for this session is incomplete, so it was not marked as ready. "
    "It may still be coming in; try again later."
)


class IngestBusyError(RuntimeError):
    """Too many fetches are already queued to accept another session."""


@dataclass(frozen=True, slots=True)
class Submission:
    job_id: str
    #: False when the caller attached to a running job or the data was cached.
    is_new: bool


class JobStore(Protocol):
    async def is_ingested(self, key: JobKey) -> bool: ...
    async def find_active(self, key: JobKey) -> str | None: ...
    async def claim(self, key: JobKey) -> str | None: ...
    async def record_cached(self, key: JobKey) -> str: ...
    async def get(self, job_id: str) -> JobRecord | None: ...
    async def start(self, job_id: str) -> None: ...
    async def advance(self, job_id: str, stage: JobStage) -> None: ...
    async def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        rows_written: int | None = None,
        error: str | None = None,
    ) -> None: ...
    async def store_session(self, raw: RawSession) -> StoredSession: ...


class SessionProvider(Protocol):
    def fetch_session(
        self, season: int, round_number: int, session_type: SessionType
    ) -> RawSession: ...


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        provider: SessionProvider,
        *,
        max_concurrent: int,
        max_pending: int,
        timeout_seconds: float,
    ) -> None:
        self._store = store
        self._provider = provider
        self._max_pending = max_pending
        self._timeout = timeout_seconds
        self._slots = asyncio.Semaphore(max_concurrent)
        self._submit_lock = asyncio.Lock()
        # Jobs this process owns, from claim until the row is finished.
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Jobs that failed here but whose failure could not be written. Their
        # rows look orphaned, but the real reason is known and is used instead.
        self._unrecorded: dict[str, str] = {}

    async def submit(self, key: JobKey) -> Submission:
        async with self._submit_lock:
            if await self._store.is_ingested(key):
                return Submission(await self._store.record_cached(key), is_new=False)

            active = await self._store.find_active(key)
            if active is not None:
                if active in self._tasks:
                    return Submission(active, is_new=False)
                await self._interrupt(active)

            if len(self._tasks) >= self._max_pending:
                raise IngestBusyError("too many fetches are already queued")

            job_id = await self._store.claim(key)
            if job_id is None:
                # Only another process could have claimed it in between.
                existing = await self._store.find_active(key)
                if existing is None:
                    raise IngestBusyError("the session is being claimed elsewhere")
                return Submission(existing, is_new=False)

            task = asyncio.create_task(self._run(job_id, key), name=f"ingest-{job_id}")
            self._tasks[job_id] = task
            task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
            return Submission(job_id, is_new=True)

    async def is_ingested(self, key: JobKey) -> bool:
        """A read-only check. Unlike `submit`, it never writes a job row."""
        return await self._store.is_ingested(key)

    async def get(self, job_id: str) -> JobRecord | None:
        record = await self._store.get(job_id)
        if record is not None and record.is_active and job_id not in self._tasks:
            await self._interrupt(job_id)
            record = await self._store.get(job_id)
        return record

    async def wait_idle(self) -> None:
        """Wait for every job this process owns. For tests and shutdown."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel running jobs. Their rows stay live and read as orphans later."""
        for task in self._tasks.values():
            task.cancel()
        await self.wait_idle()

    async def _interrupt(self, job_id: str) -> None:
        reason = self._unrecorded.get(job_id)
        if reason is None:
            logger.warning("job %s was orphaned by a restart; marking it failed", job_id)
        await self._store.finish(job_id, JobStatus.FAILED, error=reason or INTERRUPTED)
        self._unrecorded.pop(job_id, None)

    async def _run(self, job_id: str, key: JobKey) -> None:
        try:
            async with self._slots:
                await self._store.start(job_id)
                async with asyncio.timeout(self._timeout):
                    await self._ingest(job_id, key)
        except TimeoutError:
            await self._fail(job_id, f"The fetch took longer than {self._timeout:g} seconds.")
        except SessionNotAvailableError as error:
            await self._fail(job_id, _sentence(str(error)))
        except ProviderError:
            logger.exception("job %s: provider failed for %s", job_id, key)
            await self._fail(job_id, PROVIDER_FAILED)
        except Exception:
            logger.exception("job %s: unexpected failure for %s", job_id, key)
            await self._fail(job_id, UNEXPECTED)

    async def _ingest(self, job_id: str, key: JobKey) -> None:
        # Resolving: something may have stored it while this job was queued.
        if await self._store.is_ingested(key):
            await self._store.finish(job_id, JobStatus.SKIPPED_CACHED, rows_written=0)
            return

        await self._store.advance(job_id, JobStage.FETCHING)
        raw = await asyncio.to_thread(
            self._provider.fetch_session, key.season_year, key.round_number, key.session_type
        )

        await self._store.advance(job_id, JobStage.STORING)
        stored = await self._store.store_session(raw)

        await self._store.advance(job_id, JobStage.VERIFYING)
        if not stored.is_complete:
            await self._store.finish(
                job_id, JobStatus.FAILED, rows_written=stored.rows_written, error=INCOMPLETE
            )
            return
        await self._store.finish(job_id, JobStatus.SUCCEEDED, rows_written=stored.rows_written)
        logger.info("job %s stored %s: %d rows", job_id, key, stored.rows_written)

    async def _fail(self, job_id: str, message: str) -> None:
        try:
            await self._store.finish(job_id, JobStatus.FAILED, error=message)
        except Exception:
            # The row stays live; the next poll records it, with this message.
            logger.exception("job %s: could not record its failure", job_id)
            self._unrecorded[job_id] = message


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return PROVIDER_FAILED
    return text[0].upper() + text[1:] + ("" if text.endswith(".") else ".")


class PostgresJobStore:
    """`JobStore` on the writer engine, one short transaction per call.

    Short on purpose: an idle-in-transaction session keeps Neon's compute awake,
    and a fetch can take two minutes.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    async def is_ingested(self, key: JobKey) -> bool:
        async with self._db.writer.connect() as connection:
            return await jobs.is_ingested(connection, key)

    async def find_active(self, key: JobKey) -> str | None:
        async with self._db.writer.connect() as connection:
            return await jobs.find_active(connection, key)

    async def claim(self, key: JobKey) -> str | None:
        async with self._db.writer.begin() as connection:
            return await jobs.claim(connection, key)

    async def record_cached(self, key: JobKey) -> str:
        async with self._db.writer.begin() as connection:
            return await jobs.record_cached(connection, key)

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._db.writer.connect() as connection:
            return await jobs.get(connection, job_id)

    async def start(self, job_id: str) -> None:
        async with self._db.writer.begin() as connection:
            await jobs.start(connection, job_id)

    async def advance(self, job_id: str, stage: JobStage) -> None:
        async with self._db.writer.begin() as connection:
            await jobs.advance(connection, job_id, stage)

    async def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        rows_written: int | None = None,
        error: str | None = None,
    ) -> None:
        async with self._db.writer.begin() as connection:
            await jobs.finish(connection, job_id, status, rows_written=rows_written, error=error)

    async def store_session(self, raw: RawSession) -> StoredSession:
        # One transaction: either the session is complete and marked, or
        # nothing is left behind.
        async with self._db.writer.begin() as connection:
            return await SessionWriter(connection).store(raw)
