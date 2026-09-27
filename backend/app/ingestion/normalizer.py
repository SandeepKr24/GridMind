"""Writes a `RawSession` into the database.

Two properties matter more than anything else here.

**Idempotent.** Ingesting the same session twice must update rows, never
duplicate them. Every write goes through `INSERT ... ON CONFLICT` keyed on the
natural key, so a re-ingest after a data correction upstream converges on the
corrected values instead of doubling the lap count. A session's results, laps
and pit stops are cleared first, so rows the provider has since dropped go too.

**Transactional.** A failure must leave nothing behind. The caller runs this
inside one transaction, and `sessions.ingested_at` — the flag that means "this
data is complete, serve it" — is set last. If anything raises, the flag is
never set and the partial rows are rolled back with it.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import (
    Circuit,
    Constructor,
    Driver,
    DriverSeason,
    Lap,
    Meeting,
    PitStop,
    RaceControlEvent,
    Season,
    Session,
    SessionResult,
)
from app.ingestion.base import RawSession
from app.ingestion.convert import slugify

logger = logging.getLogger(__name__)

# Rows per executemany batch. Large enough that a 900-lap race is a couple of
# round trips, small enough not to build a multi-megabyte statement.
BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class StoredSession:
    """What was written, for the job row and the logs."""

    session_id: int
    meeting_id: int
    rows_written: int
    is_complete: bool


async def _upsert_returning_id(
    connection: AsyncConnection,
    table: Any,
    values: dict[str, Any],
    conflict_columns: list[str],
) -> int:
    """Insert or update one row, and return its primary key either way.

    `ON CONFLICT DO UPDATE` rather than `DO NOTHING`, because `DO NOTHING`
    returns no row on conflict and we would need a second round trip to find
    the id. Updating a row to its own values is cheap and always returns it.
    """
    base = insert(table).values(**values)
    updatable = {key: base.excluded[key] for key in values if key not in conflict_columns}
    statement = base.on_conflict_do_update(
        index_elements=conflict_columns,
        set_=updatable or {conflict_columns[0]: base.excluded[conflict_columns[0]]},
    ).returning(table.id)
    result = await connection.execute(statement)
    return int(result.scalar_one())


async def _bulk_upsert(
    connection: AsyncConnection,
    table: Any,
    rows: list[dict[str, Any]],
    conflict_columns: list[str],
) -> int:
    """Upsert many rows of the same shape. Returns the number sent."""
    if not rows:
        return 0
    written = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        statement = insert(table)
        updatable = {
            key: statement.excluded[key] for key in batch[0] if key not in conflict_columns
        }
        statement = statement.on_conflict_do_update(index_elements=conflict_columns, set_=updatable)
        await connection.execute(statement, batch)
        written += len(batch)
    return written


class SessionWriter:
    """Stores one fetched session. Call inside a transaction."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def store(self, raw: RawSession) -> StoredSession:
        season_id = await self._season(raw.event.season)
        circuit_id = await self._circuit(raw)
        meeting_id = await self._meeting(raw, season_id, circuit_id)
        session_id = await self._session(raw, meeting_id)

        driver_ids, constructor_ids = await self._people(raw, season_id)
        await self._clear_timing(session_id)

        written = 0
        written += await self._results(raw, session_id, driver_ids, constructor_ids)
        written += await self._laps(raw, session_id, driver_ids)
        written += await self._pit_stops(raw, session_id, driver_ids)
        written += await self._race_control(raw, session_id, driver_ids)

        # Last, and only when the data is whole. A partial session stays
        # unmarked so the next request re-fetches rather than serving gaps as
        # if they were the truth.
        is_complete = not raw.is_partial
        if is_complete:
            await self._mark_ingested(session_id)

        logger.info(
            "stored %s %s round %s: %d rows, complete=%s",
            raw.event.season,
            raw.session_type.value,
            raw.event.round_number,
            written,
            is_complete,
        )
        return StoredSession(
            session_id=session_id,
            meeting_id=meeting_id,
            rows_written=written,
            is_complete=is_complete,
        )

    # -- spine ---------------------------------------------------------

    async def _season(self, year: int) -> int:
        return await _upsert_returning_id(self._connection, Season, {"year": year}, ["year"])

    async def _circuit(self, raw: RawSession) -> int | None:
        """Circuits are keyed on a slug of the venue.

        FastF1's schedule gives a display location but no stable circuit id, so
        the slug is the natural key. A weekend with no location — which happens
        in sparse historic data — gets no circuit rather than a fabricated one.
        """
        key = slugify(raw.event.location) or slugify(raw.event.country)
        if key is None:
            return None
        return await _upsert_returning_id(
            self._connection,
            Circuit,
            {
                "circuit_key": key,
                "name": raw.event.location or raw.event.country or key,
                "location": raw.event.location,
                "country": raw.event.country,
            },
            ["circuit_key"],
        )

    async def _meeting(self, raw: RawSession, season_id: int, circuit_id: int | None) -> int:
        return await _upsert_returning_id(
            self._connection,
            Meeting,
            {
                "season_id": season_id,
                "circuit_id": circuit_id,
                "round_number": raw.event.round_number,
                "event_name": raw.event.event_name,
                "event_date": raw.event.event_date,
            },
            ["season_id", "round_number"],
        )

    async def _session(self, raw: RawSession, meeting_id: int) -> int:
        # ingested_at is deliberately absent: it is set at the end, and listing
        # it here would clear it on every re-ingest before the work is done.
        return await _upsert_returning_id(
            self._connection,
            Session,
            {
                "meeting_id": meeting_id,
                "session_type": raw.session_type,
                "session_date": raw.session_date,
            },
            ["meeting_id", "session_type"],
        )

    async def _clear_timing(self, session_id: int) -> None:
        """Drop the session's previous results, laps and pit stops.

        Upserts alone would keep a row the provider has since removed, such as
        a lap struck from the data, so a re-ingest starts from nothing. Readers
        see the old rows until the caller's transaction commits.
        """
        for table in (SessionResult, Lap, PitStop):
            await self._connection.execute(delete(table).where(table.session_id == session_id))

    async def _mark_ingested(self, session_id: int) -> None:
        await self._connection.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(ingested_at=dt.datetime.now(dt.UTC))
        )

    # -- people --------------------------------------------------------

    async def _people(
        self, raw: RawSession, season_id: int
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Upsert drivers and constructors, and return ref-to-id maps."""
        driver_ids: dict[str, int] = {}
        constructor_ids: dict[str, int] = {}

        for entry in raw.drivers:
            if entry.constructor_ref and entry.constructor_ref not in constructor_ids:
                constructor_ids[entry.constructor_ref] = await _upsert_returning_id(
                    self._connection,
                    Constructor,
                    {
                        "constructor_ref": entry.constructor_ref,
                        "name": entry.constructor_name or entry.constructor_ref,
                    },
                    ["constructor_ref"],
                )

            driver_ids[entry.driver_ref] = await _upsert_returning_id(
                self._connection,
                Driver,
                {
                    "driver_ref": entry.driver_ref,
                    "driver_code": entry.code,
                    "first_name": entry.first_name,
                    "last_name": entry.last_name,
                    "full_name": entry.full_name,
                    "nationality": entry.nationality,
                    "permanent_number": entry.number,
                },
                ["driver_ref"],
            )

        # Who drove for whom this season. A mid-season change simply adds a
        # second row; the unique key includes the constructor.
        pairings = [
            {
                "season_id": season_id,
                "driver_id": driver_ids[entry.driver_ref],
                "constructor_id": constructor_ids[entry.constructor_ref],
                "car_number": entry.number,
            }
            for entry in raw.drivers
            if entry.constructor_ref in constructor_ids
        ]
        await _bulk_upsert(
            self._connection,
            DriverSeason,
            pairings,
            ["season_id", "driver_id", "constructor_id"],
        )
        return driver_ids, constructor_ids

    # -- session data --------------------------------------------------

    async def _results(
        self,
        raw: RawSession,
        session_id: int,
        driver_ids: dict[str, int],
        constructor_ids: dict[str, int],
    ) -> int:
        constructor_by_driver = {
            entry.driver_ref: constructor_ids.get(entry.constructor_ref or "")
            for entry in raw.drivers
        }
        rows = [
            {
                "session_id": session_id,
                "driver_id": driver_ids[result.driver_ref],
                "constructor_id": constructor_by_driver.get(result.driver_ref),
                "position": result.position,
                "grid_position": result.grid_position,
                "points": result.points,
                "status": result.status,
                "total_laps": result.laps_completed,
                "fastest_lap": False,
                "fastest_lap_time_ms": None,
                "q1_time_ms": result.q1_time_ms,
                "q2_time_ms": result.q2_time_ms,
                "q3_time_ms": result.q3_time_ms,
                "gap_to_winner_ms": result.gap_to_winner_ms,
                "race_time_ms": result.race_time_ms,
            }
            for result in raw.results
            if result.driver_ref in driver_ids
        ]
        self._mark_fastest_lap(raw, rows, driver_ids)
        return await _bulk_upsert(
            self._connection, SessionResult, rows, ["session_id", "driver_id"]
        )

    @staticmethod
    def _mark_fastest_lap(
        raw: RawSession, rows: list[dict[str, Any]], driver_ids: dict[str, int]
    ) -> None:
        """Derived, because the classification does not carry it.

        Only laps that actually counted are eligible: a deleted lap was struck
        from the timing sheets, so awarding it the fastest lap would contradict
        the official result.
        """
        best_driver, best_time = None, None
        for lap in raw.laps:
            if lap.lap_time_ms is None or lap.is_deleted:
                continue
            if best_time is None or lap.lap_time_ms < best_time:
                best_driver, best_time = lap.driver_ref, lap.lap_time_ms

        if best_driver is None or best_driver not in driver_ids:
            return
        target = driver_ids[best_driver]
        for row in rows:
            if row["driver_id"] == target:
                row["fastest_lap"] = True
                row["fastest_lap_time_ms"] = best_time
                return

    async def _laps(self, raw: RawSession, session_id: int, driver_ids: dict[str, int]) -> int:
        rows = [
            {
                "session_id": session_id,
                "driver_id": driver_ids[lap.driver_ref],
                "lap_number": lap.lap_number,
                "lap_time_ms": lap.lap_time_ms,
                "sector_1_ms": lap.sector_1_ms,
                "sector_2_ms": lap.sector_2_ms,
                "sector_3_ms": lap.sector_3_ms,
                "speed_trap_kph": lap.speed_trap_kph,
                "position": lap.position,
                "compound": lap.compound,
                "tyre_life": lap.tyre_life,
                "is_personal_best": lap.is_personal_best,
                "track_status": lap.track_status,
            }
            for lap in raw.laps
            if lap.driver_ref in driver_ids
        ]
        return await _bulk_upsert(
            self._connection, Lap, rows, ["session_id", "driver_id", "lap_number"]
        )

    async def _pit_stops(self, raw: RawSession, session_id: int, driver_ids: dict[str, int]) -> int:
        rows = [
            {
                "session_id": session_id,
                "driver_id": driver_ids[stop.driver_ref],
                "stop_number": stop.stop_number,
                "lap_number": stop.lap_number,
                "duration_ms": stop.duration_ms,
            }
            for stop in raw.pit_stops
            if stop.driver_ref in driver_ids
        ]
        return await _bulk_upsert(
            self._connection, PitStop, rows, ["session_id", "driver_id", "stop_number"]
        )

    async def _race_control(
        self, raw: RawSession, session_id: int, driver_ids: dict[str, int]
    ) -> int:
        """Replace wholesale, because these messages have no natural key.

        Two identical messages can legitimately occur in one session, so there
        is nothing to upsert on. Deleting this session's messages first keeps a
        re-ingest from accumulating copies.
        """
        await self._connection.execute(
            delete(RaceControlEvent).where(RaceControlEvent.session_id == session_id)
        )
        if not raw.race_control:
            return 0

        numbers = await self._driver_numbers(driver_ids)
        rows = [
            {
                "session_id": session_id,
                "driver_id": (
                    numbers.get(message.driver_number)
                    if message.driver_number is not None
                    else None
                ),
                "timestamp": message.timestamp,
                "lap_number": message.lap_number,
                "category": message.category,
                "flag": message.flag,
                "scope": message.scope,
                "message": message.message,
            }
            for message in raw.race_control
        ]
        for start in range(0, len(rows), BATCH_SIZE):
            await self._connection.execute(
                insert(RaceControlEvent), rows[start : start + BATCH_SIZE]
            )
        return len(rows)

    async def _driver_numbers(self, driver_ids: dict[str, int]) -> dict[int, int]:
        """Car number to driver id, for race control messages.

        Race control identifies a driver by racing number, which is the only
        place that number is used as a key.
        """
        if not driver_ids:
            return {}
        result = await self._connection.execute(
            select(Driver.permanent_number, Driver.id).where(Driver.id.in_(driver_ids.values()))
        )
        return {number: driver_id for number, driver_id in result if number is not None}
