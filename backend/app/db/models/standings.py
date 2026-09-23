"""Championship standings, cached from jolpica-f1.

These cannot be derived from what we store. On-demand ingestion means the
database holds only the sessions somebody asked about, so summing points across
our own rows would give a total based on an arbitrary subset of the season.
Standings therefore come from an external source and are cached, with
`fetched_at` recording how stale the answer is.

jolpica-f1 is the free community successor to Ergast, which was retired.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, pk, utc_now


class DriverStanding(Base):
    __tablename__ = "driver_standings"
    __table_args__ = (UniqueConstraint("season_id", "round_number", "driver_id"),)

    id: Mapped[int] = pk()
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    constructor_id: Mapped[int | None] = mapped_column(
        ForeignKey("constructors.id", ondelete="SET NULL"), index=True
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    points: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    wins: Mapped[int | None] = mapped_column(SmallInteger)
    fetched_at: Mapped[dt.datetime] = utc_now()


class ConstructorStanding(Base):
    __tablename__ = "constructor_standings"
    __table_args__ = (UniqueConstraint("season_id", "round_number", "constructor_id"),)

    id: Mapped[int] = pk()
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    constructor_id: Mapped[int] = mapped_column(
        ForeignKey("constructors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position: Mapped[int | None] = mapped_column(SmallInteger)
    points: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    wins: Mapped[int | None] = mapped_column(SmallInteger)
    fetched_at: Mapped[dt.datetime] = utc_now()


class StandingsFetch(Base):
    """When each season's standings were last pulled.

    Without this, a season with no standings rows is indistinguishable from one
    we simply have not fetched yet, and the cache TTL has nothing to measure.
    """

    __tablename__ = "standings_fetches"
    __table_args__ = (UniqueConstraint("season_id", "round_number"),)

    id: Mapped[int] = pk()
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fetched_at: Mapped[dt.datetime] = utc_now()
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="jolpica")
