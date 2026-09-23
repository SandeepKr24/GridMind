"""Ingest one session by hand.

    python -m scripts.ingest_session --year 2024 --round 14 --session race

A debugging and operations aid, not a production path. The API triggers
ingestion through the job runner; this bypasses the job row and writes
directly, which makes it useful for checking a provider change against a real
session without going through the queue.

Re-running is safe: storage is idempotent. `--force` re-fetches and rewrites a
session already marked ingested, for the case where the provider corrects data
after the fact.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select

from app.config import Settings
from app.db.database import Database
from app.db.models import Meeting, Season, Session
from app.db.models.enums import SessionType
from app.ingestion.base import ProviderError
from app.ingestion.fastf1_provider import FastF1Provider
from app.ingestion.normalizer import SessionWriter
from app.runtime import configure_event_loop

logger = logging.getLogger("ingest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest one F1 session.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    parser.add_argument(
        "--session",
        required=True,
        choices=[s.value for s in SessionType],
        help="whole sessions only; qualifying segments are columns, not sessions",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-fetch and rewrite even if the session is already stored",
    )
    return parser.parse_args(argv)


async def already_stored(
    database: Database, year: int, round_number: int, session_type: SessionType
) -> bool:
    async with database.writer.connect() as connection:
        result = await connection.execute(
            select(Session.ingested_at)
            .join(Meeting, Meeting.id == Session.meeting_id)
            .join(Season, Season.id == Meeting.season_id)
            .where(Season.year == year)
            .where(Meeting.round_number == round_number)
            .where(Session.session_type == session_type)
        )
        ingested_at = result.scalar_one_or_none()
    return ingested_at is not None


async def run(args: argparse.Namespace) -> int:
    settings = Settings()  # type: ignore[call-arg]
    session_type = SessionType(args.session)
    database = Database(settings)

    try:
        if not args.force and await already_stored(
            database, args.year, args.round_number, session_type
        ):
            logger.info(
                "%s round %s %s is already stored; use --force to re-ingest",
                args.year,
                args.round_number,
                session_type.value,
            )
            return 0

        provider = FastF1Provider(settings.fastf1_cache_dir)
        logger.info(
            "fetching %s round %s %s (30-120s on a cold cache)",
            args.year,
            args.round_number,
            session_type.value,
        )
        # Blocking and CPU-heavy, so it runs off the event loop.
        raw = await asyncio.to_thread(
            provider.fetch_session, args.year, args.round_number, session_type
        )
        logger.info(
            "fetched %s: %d rows%s",
            raw.event.event_name,
            raw.row_count,
            f" ({'; '.join(raw.warnings)})" if raw.warnings else "",
        )

        # One transaction: either the session is complete and marked, or
        # nothing is left behind.
        async with database.writer.begin() as connection:
            stored = await SessionWriter(connection).store(raw)

        logger.info(
            "stored session %d: %d rows, complete=%s",
            stored.session_id,
            stored.rows_written,
            stored.is_complete,
        )
        return 0

    except ProviderError as error:
        logger.error("%s", error)
        return 1
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    configure_event_loop()
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
