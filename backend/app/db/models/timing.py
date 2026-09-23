"""Per-session timing data: results, laps, pit stops and race control.

All durations are stored as integer milliseconds rather than intervals or
floats. The agent writes SQL against these columns, and integers compare, sum
and average without the surprises that float seconds bring to questions like
"who was fastest".
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, pk


class SessionResult(Base):
    """The classification for one driver in one session.

    `q1_time_ms` / `q2_time_ms` / `q3_time_ms` are null outside qualifying.
    They exist so segment questions can be answered without modelling Q1/Q2/Q3
    as separate sessions.
    """

    __tablename__ = "session_results"
    __table_args__ = (UniqueConstraint("session_id", "driver_id"),)

    id: Mapped[int] = pk()
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    constructor_id: Mapped[int | None] = mapped_column(
        ForeignKey("constructors.id", ondelete="SET NULL"), index=True
    )

    # Null for a driver who did not classify.
    position: Mapped[int | None] = mapped_column(SmallInteger)
    grid_position: Mapped[int | None] = mapped_column(SmallInteger)
    points: Mapped[float | None] = mapped_column(Numeric(6, 2))
    # "Finished", "+1 Lap", "Accident", "Gearbox"...
    status: Mapped[str | None] = mapped_column(String(64))
    total_laps: Mapped[int | None] = mapped_column(SmallInteger)

    fastest_lap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fastest_lap_time_ms: Mapped[int | None] = mapped_column(Integer)

    q1_time_ms: Mapped[int | None] = mapped_column(Integer)
    q2_time_ms: Mapped[int | None] = mapped_column(Integer)
    q3_time_ms: Mapped[int | None] = mapped_column(Integer)


class Lap(Base):
    """One timed lap.

    The largest table by far, so it carries a composite index matching how it
    is actually queried: a driver's laps within one session, in order.
    """

    __tablename__ = "laps"
    __table_args__ = (
        UniqueConstraint("session_id", "driver_id", "lap_number"),
        Index("ix_laps_session_id_driver_id_lap_number", "session_id", "driver_id", "lap_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lap_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Null on an in-lap, out-lap or deleted lap: the lap happened, but has no
    # representative time. Storing null rather than 0 keeps averages honest.
    lap_time_ms: Mapped[int | None] = mapped_column(Integer)
    sector_1_ms: Mapped[int | None] = mapped_column(Integer)
    sector_2_ms: Mapped[int | None] = mapped_column(Integer)
    sector_3_ms: Mapped[int | None] = mapped_column(Integer)
    speed_trap_kph: Mapped[float | None] = mapped_column(Numeric(6, 2))

    position: Mapped[int | None] = mapped_column(SmallInteger)
    compound: Mapped[str | None] = mapped_column(String(16), index=True)
    tyre_life: Mapped[int | None] = mapped_column(SmallInteger)
    is_personal_best: Mapped[bool | None] = mapped_column(Boolean)
    # A lap run under yellow or safety car is not comparable race pace, and
    # every pace question needs to be able to exclude it.
    track_status: Mapped[str | None] = mapped_column(String(16))


class PitStop(Base):
    __tablename__ = "pit_stops"
    __table_args__ = (UniqueConstraint("session_id", "driver_id", "stop_number"),)

    id: Mapped[int] = pk()
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stop_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lap_number: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class RaceControlEvent(Base):
    """Flags, safety cars, investigations and penalties.

    `driver_id` is null for session-wide events such as a red flag.
    """

    __tablename__ = "race_control_events"
    __table_args__ = (
        Index("ix_race_control_events_session_id_timestamp", "session_id", "timestamp"),
    )

    id: Mapped[int] = pk()
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    lap_number: Mapped[int | None] = mapped_column(SmallInteger)
    category: Mapped[str | None] = mapped_column(String(32))
    flag: Mapped[str | None] = mapped_column(String(32))
    scope: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, nullable=False)
