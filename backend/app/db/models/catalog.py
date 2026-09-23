"""The calendar and the people in it.

These tables are the stable spine: seasons, circuits, meetings, sessions,
drivers and constructors. Everything in `timing.py` hangs off a session and a
driver here.

Natural keys carry unique constraints throughout, because ingestion is
idempotent by design — asking twice for the same race must update rows rather
than duplicate them.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, pg_enum, pk
from app.db.models.enums import SessionType


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = pk()
    year: Mapped[int] = mapped_column(SmallInteger, unique=True, nullable=False)

    meetings: Mapped[list[Meeting]] = relationship(back_populates="season")


class Circuit(Base):
    __tablename__ = "circuits"

    id: Mapped[int] = pk()
    # FastF1's stable identifier for the venue, e.g. "monza".
    circuit_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))
    # Numeric, not float: coordinates are compared for equality on re-ingest.
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))


class Meeting(Base):
    """A Grand Prix weekend. The frontend addresses these as `{year}-{round}`."""

    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("season_id", "round_number"),
        Index("ix_meetings_event_date", "event_date"),
    )

    id: Mapped[int] = pk()
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    circuit_id: Mapped[int | None] = mapped_column(
        ForeignKey("circuits.id", ondelete="SET NULL"), index=True
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    event_name: Mapped[str] = mapped_column(String(160), nullable=False)
    event_date: Mapped[dt.date | None] = mapped_column(Date)

    season: Mapped[Season] = relationship(back_populates="meetings")
    sessions: Mapped[list[Session]] = relationship(back_populates="meeting")


class Session(Base):
    """One session of a weekend, stored whole.

    `ingested_at` is the cache flag the whole on-demand design turns on: null
    means the timing data is not stored yet, so a question about this session
    has to trigger an ingestion job first.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("meeting_id", "session_type"),
        Index("ix_sessions_ingested_at", "ingested_at"),
    )

    id: Mapped[int] = pk()
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_type: Mapped[SessionType] = mapped_column(
        pg_enum(SessionType, "session_type"), nullable=False
    )
    session_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    meeting: Mapped[Meeting] = relationship(back_populates="sessions")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = pk()
    # The three-letter code (VER, NOR). Not unique across history: codes are
    # reused, and pre-2014 entries may have none.
    driver_code: Mapped[str | None] = mapped_column(String(8), index=True)
    # FastF1's stable per-driver reference, e.g. "max_verstappen".
    driver_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(64))
    last_name: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    nationality: Mapped[str | None] = mapped_column(String(64))
    permanent_number: Mapped[int | None] = mapped_column(SmallInteger)


class Constructor(Base):
    __tablename__ = "constructors"

    id: Mapped[int] = pk()
    constructor_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    nationality: Mapped[str | None] = mapped_column(String(64))


class DriverSeason(Base):
    """Who drove for whom in a given year.

    Needed because a driver changes team between seasons, and mid-season, so
    "which team was X driving for?" has no single answer without this.
    """

    __tablename__ = "driver_seasons"
    __table_args__ = (UniqueConstraint("season_id", "driver_id", "constructor_id"),)

    id: Mapped[int] = pk()
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    constructor_id: Mapped[int] = mapped_column(
        ForeignKey("constructors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    car_number: Mapped[int | None] = mapped_column(Integer)
