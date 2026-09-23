"""Read queries behind the race endpoints.

Everything here runs on the **reader** connection, so it is physically
incapable of writing. The SQL is ours, not the agent's — but using the same
restricted role keeps one path for reads and removes any chance of an endpoint
mutating data by accident.

Nothing is invented. Where the database has no answer the field is null and the
frontend shows an empty state, which is the whole point of the architecture.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.schemas.race import (
    CalendarRound,
    ClassificationRow,
    DriverPaceTrace,
    DriverStrategy,
    LapPacePoint,
    PitStopRow,
    PositionChange,
    RaceControlEventOut,
    RaceDetail,
    RaceStats,
    RaceSummary,
    TyreStint,
    format_lap_time,
    iso,
    race_id,
)
from app.db.models import (
    Circuit,
    Constructor,
    Driver,
    Lap,
    Meeting,
    PitStop,
    RaceControlEvent,
    Season,
    Session,
    SessionResult,
)
from app.db.models.enums import SessionType

#: Race control categories that mean the safety car was deployed.
SAFETY_CAR_FLAGS = ("SAFETY CAR", "VIRTUAL SAFETY CAR")


def _race_session() -> Select[tuple[int, int, int]]:
    """Session id, season year and round for every stored race session."""
    return (
        select(Session.id, Season.year, Meeting.round_number)
        .join(Meeting, Meeting.id == Session.meeting_id)
        .join(Season, Season.id == Meeting.season_id)
        .where(Session.session_type == SessionType.RACE)
    )


def _state(ingested_at: dt.datetime | None, event_date: dt.date | None) -> str:
    """The three-state badge on the race list.

    `ingested` means the timing data is stored and questions are instant.
    `upcoming` means the race has not run. `available` is the middle case: it
    has run, and asking about it will trigger a cold fetch.
    """
    if ingested_at is not None:
        return "ingested"
    today = dt.datetime.now(dt.UTC).date()
    if event_date is not None and event_date > today:
        return "upcoming"
    return "available"


async def get_calendar(connection: AsyncConnection, season: int) -> list[CalendarRound]:
    """The season's rounds, with what we hold for each.

    Built only from stored meetings. A season nobody has asked about yet
    returns an empty list rather than a fabricated calendar — fetching the real
    one is the ingestion path's job.
    """
    race = Session.__table__.alias("race_session")
    statement = (
        select(
            Season.year,
            Meeting.round_number,
            Meeting.event_name,
            Meeting.event_date,
            Circuit.name.label("circuit_name"),
            Circuit.country,
            race.c.ingested_at,
            race.c.id.label("session_id"),
        )
        .select_from(Meeting)
        .join(Season, Season.id == Meeting.season_id)
        .outerjoin(Circuit, Circuit.id == Meeting.circuit_id)
        .outerjoin(
            race,
            (race.c.meeting_id == Meeting.id) & (race.c.session_type == SessionType.RACE),
        )
        .where(Season.year == season)
        .order_by(Meeting.round_number)
    )

    rows = (await connection.execute(statement)).all()
    if not rows:
        return []

    lap_counts = await _lap_counts(connection, [r.session_id for r in rows if r.session_id])

    return [
        CalendarRound(
            season=row.year,
            round=row.round_number,
            event_name=row.event_name,
            circuit_name=row.circuit_name or row.event_name,
            country=row.country,
            event_date=iso(row.event_date) or "",
            state=_state(row.ingested_at, row.event_date),  # type: ignore[arg-type]
            total_laps=lap_counts.get(row.session_id),
        )
        for row in rows
    ]


async def _lap_counts(connection: AsyncConnection, session_ids: list[int]) -> dict[int, int]:
    """Laps completed by the winner, i.e. the race distance.

    One grouped query rather than one per round: a 24-round calendar would
    otherwise be 24 round trips to Neon.
    """
    if not session_ids:
        return {}
    statement = (
        select(Lap.session_id, func.max(Lap.lap_number))
        .where(Lap.session_id.in_(session_ids))
        .group_by(Lap.session_id)
    )
    return {sid: count for sid, count in (await connection.execute(statement)).all()}


async def _resolve_session(
    connection: AsyncConnection, season: int, round_number: int
) -> int | None:
    statement = _race_session().where(Season.year == season, Meeting.round_number == round_number)
    row = (await connection.execute(statement)).first()
    return int(row[0]) if row else None


async def get_race(
    connection: AsyncConnection, season: int, round_number: int
) -> RaceDetail | None:
    race = Session.__table__.alias("race_session")
    statement = (
        select(
            Season.year,
            Meeting.round_number,
            Meeting.event_name,
            Meeting.event_date,
            Circuit.name.label("circuit_name"),
            race.c.id.label("session_id"),
            race.c.ingested_at,
        )
        .select_from(Meeting)
        .join(Season, Season.id == Meeting.season_id)
        .outerjoin(Circuit, Circuit.id == Meeting.circuit_id)
        .outerjoin(
            race,
            (race.c.meeting_id == Meeting.id) & (race.c.session_type == SessionType.RACE),
        )
        .where(Season.year == season, Meeting.round_number == round_number)
    )
    row = (await connection.execute(statement)).first()
    if row is None:
        return None

    winner_name: str | None = None
    fastest_time: str | None = None
    fastest_driver: str | None = None
    total_laps: int | None = None
    safety_cars: int | None = None

    if row.session_id is not None:
        winner_name = await _winner(connection, row.session_id)
        fastest_driver, fastest_time = await _fastest_lap(connection, row.session_id)
        total_laps = (await _lap_counts(connection, [row.session_id])).get(row.session_id)
        safety_cars = await _safety_car_periods(connection, row.session_id)

    return RaceDetail(
        id=race_id(row.year, row.round_number),
        season=row.year,
        round=row.round_number,
        event_name=row.event_name,
        circuit_name=row.circuit_name or row.event_name,
        event_date=iso(row.event_date) or "",
        state=_state(row.ingested_at, row.event_date),  # type: ignore[arg-type]
        winner_name=winner_name,
        has_report=False,
        total_laps=total_laps,
        fastest_lap_time=fastest_time,
        fastest_lap_driver=fastest_driver,
        safety_car_periods=safety_cars,
        # Requires the race-time gap, which we do not store. Null rather than
        # a guess.
        winning_margin=None,
    )


async def _winner(connection: AsyncConnection, session_id: int) -> str | None:
    statement = (
        select(Driver.full_name)
        .join(SessionResult, SessionResult.driver_id == Driver.id)
        .where(SessionResult.session_id == session_id, SessionResult.position == 1)
    )
    return (await connection.execute(statement)).scalar_one_or_none()


async def _fastest_lap(
    connection: AsyncConnection, session_id: int
) -> tuple[str | None, str | None]:
    statement = (
        select(Driver.full_name, SessionResult.fastest_lap_time_ms)
        .join(SessionResult, SessionResult.driver_id == Driver.id)
        .where(
            SessionResult.session_id == session_id,
            SessionResult.fastest_lap.is_(True),
        )
    )
    row = (await connection.execute(statement)).first()
    if row is None:
        return None, None
    return row[0], format_lap_time(row[1])


async def _safety_car_periods(connection: AsyncConnection, session_id: int) -> int:
    """Counted from race control messages, since nothing else records it."""
    conditions = [RaceControlEvent.message.ilike(f"%{flag}%") for flag in SAFETY_CAR_FLAGS]
    statement = (
        select(func.count())
        .select_from(RaceControlEvent)
        .where(RaceControlEvent.session_id == session_id)
        .where(RaceControlEvent.category == "SafetyCar")
    )
    count = (await connection.execute(statement)).scalar_one()
    if count:
        return int(count)

    # Older seasons do not set the category, so fall back to the text.
    from sqlalchemy import or_

    statement = (
        select(func.count())
        .select_from(RaceControlEvent)
        .where(RaceControlEvent.session_id == session_id)
        .where(or_(*conditions))
    )
    return int((await connection.execute(statement)).scalar_one())


async def get_race_stats(
    connection: AsyncConnection, season: int, round_number: int
) -> RaceStats | None:
    session_id = await _resolve_session(connection, season, round_number)
    if session_id is None:
        return None

    classification = await _classification(connection, session_id)
    return RaceStats(
        classification=classification,
        position_changes=_position_changes(classification),
        pace_traces=await _pace_traces(connection, session_id),
        strategies=await _strategies(connection, session_id),
        pit_stops=await _pit_stops(connection, session_id),
        race_control=await _race_control(connection, session_id),
    )


async def _classification(connection: AsyncConnection, session_id: int) -> list[ClassificationRow]:
    stops = (
        select(PitStop.driver_id, func.count().label("stop_count"))
        .where(PitStop.session_id == session_id)
        .group_by(PitStop.driver_id)
        .subquery()
    )
    best = (
        select(Lap.driver_id, func.min(Lap.lap_time_ms).label("best_ms"))
        .where(Lap.session_id == session_id, Lap.lap_time_ms.is_not(None))
        .group_by(Lap.driver_id)
        .subquery()
    )
    statement = (
        select(
            SessionResult.position,
            SessionResult.grid_position,
            SessionResult.points,
            SessionResult.status,
            Driver.full_name,
            Driver.driver_code,
            Constructor.name.label("constructor_name"),
            stops.c.stop_count,
            best.c.best_ms,
        )
        .select_from(SessionResult)
        .join(Driver, Driver.id == SessionResult.driver_id)
        .outerjoin(Constructor, Constructor.id == SessionResult.constructor_id)
        .outerjoin(stops, stops.c.driver_id == SessionResult.driver_id)
        .outerjoin(best, best.c.driver_id == SessionResult.driver_id)
        .where(SessionResult.session_id == session_id)
        .order_by(SessionResult.position.nulls_last())
    )
    rows = (await connection.execute(statement)).all()

    return [
        ClassificationRow(
            position=row.position or 0,
            driver_name=row.full_name,
            driver_code=row.driver_code or "",
            constructor_name=row.constructor_name or "",
            grid_position=row.grid_position,
            points=float(row.points or 0),
            status=row.status or "",
            best_lap_time=format_lap_time(row.best_ms),
            pit_stop_count=row.stop_count,
            # Always null. "Gap to leader" means the race finishing gap, and we
            # do not store race time — only lap times. An earlier draft filled
            # it with a best-lap delta, which is a different number wearing
            # this one's name. The UI shows a dash instead.
            gap_to_leader=None,
        )
        for row in rows
    ]


def _position_changes(rows: list[ClassificationRow]) -> list[PositionChange]:
    """Who gained and lost places, biggest mover first."""
    changes = [
        PositionChange(
            driver_name=row.driver_name,
            driver_code=row.driver_code,
            grid_position=row.grid_position or 0,
            finish_position=row.position,
            positions_gained=(row.grid_position or 0) - row.position,
        )
        for row in rows
        if row.grid_position and row.position
    ]
    return sorted(changes, key=lambda c: c.positions_gained, reverse=True)


async def _pace_traces(connection: AsyncConnection, session_id: int) -> list[DriverPaceTrace]:
    """Lap times for the top finishers.

    Limited to the podium: a 20-driver trace is unreadable on a chart and would
    ship a megabyte of JSON to a phone.
    """
    podium = (
        select(SessionResult.driver_id)
        .where(SessionResult.session_id == session_id)
        .where(SessionResult.position.is_not(None))
        .order_by(SessionResult.position)
        .limit(3)
        .subquery()
    )
    statement = (
        select(Driver.driver_code, Driver.full_name, Lap.lap_number, Lap.lap_time_ms)
        .join(Driver, Driver.id == Lap.driver_id)
        .where(Lap.session_id == session_id)
        .where(Lap.driver_id.in_(select(podium.c.driver_id)))
        .where(Lap.lap_time_ms.is_not(None))
        .order_by(Driver.driver_code, Lap.lap_number)
    )
    traces: dict[str, DriverPaceTrace] = {}
    for code, name, lap_number, lap_time_ms in (await connection.execute(statement)).all():
        trace = traces.setdefault(
            code or name, DriverPaceTrace(driver_code=code or "", driver_name=name, laps=[])
        )
        trace.laps.append(LapPacePoint(lap_number=lap_number, lap_time_ms=lap_time_ms))
    return list(traces.values())


async def _strategies(connection: AsyncConnection, session_id: int) -> list[DriverStrategy]:
    """Tyre stints, rebuilt from per-lap compound data.

    A stint is a run of consecutive laps on one compound. FastF1 gives the
    compound per lap, not the stint, so the boundaries are derived here.
    """
    statement = (
        select(Driver.full_name, Driver.driver_code, Lap.lap_number, Lap.compound)
        .join(Driver, Driver.id == Lap.driver_id)
        .where(Lap.session_id == session_id, Lap.compound.is_not(None))
        .order_by(Driver.full_name, Lap.lap_number)
    )
    rows = (await connection.execute(statement)).all()

    strategies: dict[str, DriverStrategy] = {}
    for name, code, lap_number, compound in rows:
        strategy = strategies.setdefault(
            name, DriverStrategy(driver_name=name, driver_code=code or "", stop_count=0, stints=[])
        )
        stints = strategy.stints
        if stints and stints[-1].compound == compound and stints[-1].end_lap == lap_number - 1:
            stints[-1].end_lap = lap_number
        else:
            stints.append(TyreStint(compound=compound, start_lap=lap_number, end_lap=lap_number))

    for strategy in strategies.values():
        # Stops are the changes between stints, not the stints themselves.
        strategy.stop_count = max(len(strategy.stints) - 1, 0)
    return list(strategies.values())


async def _pit_stops(connection: AsyncConnection, session_id: int) -> list[PitStopRow]:
    statement = (
        select(Driver.full_name, Driver.driver_code, PitStop.lap_number, PitStop.duration_ms)
        .join(Driver, Driver.id == PitStop.driver_id)
        .where(PitStop.session_id == session_id, PitStop.duration_ms.is_not(None))
        .order_by(PitStop.duration_ms)
    )
    return [
        PitStopRow(
            driver_name=name,
            driver_code=code or "",
            lap=lap_number or 0,
            duration_seconds=round(duration_ms / 1000, 3),
        )
        for name, code, lap_number, duration_ms in (await connection.execute(statement)).all()
    ]


async def _race_control(connection: AsyncConnection, session_id: int) -> list[RaceControlEventOut]:
    statement = (
        select(
            RaceControlEvent.lap_number,
            RaceControlEvent.category,
            RaceControlEvent.flag,
            RaceControlEvent.message,
            RaceControlEvent.timestamp,
        )
        .where(RaceControlEvent.session_id == session_id)
        .order_by(RaceControlEvent.timestamp.nulls_last(), RaceControlEvent.id)
    )
    return [
        RaceControlEventOut(
            lap=lap_number,
            event_type=flag or category or "Message",
            message=message,
            timestamp=iso(timestamp),
        )
        for lap_number, category, flag, message, timestamp in (
            await connection.execute(statement)
        ).all()
    ]


async def get_dashboard(connection: AsyncConnection, season: int) -> DashboardData:
    """Counts for the dashboard, plus the most recent stored race."""
    rounds_on_calendar = int(
        (
            await connection.execute(
                select(func.count())
                .select_from(Meeting)
                .join(Season, Season.id == Meeting.season_id)
                .where(Season.year == season)
            )
        ).scalar_one()
    )
    rounds_ingested = int(
        (
            await connection.execute(
                select(func.count())
                .select_from(Session)
                .join(Meeting, Meeting.id == Session.meeting_id)
                .join(Season, Season.id == Meeting.season_id)
                .where(Season.year == season)
                .where(Session.session_type == SessionType.RACE)
                .where(Session.ingested_at.is_not(None))
            )
        ).scalar_one()
    )
    laps_stored = int(
        (
            await connection.execute(
                select(func.count())
                .select_from(Lap)
                .join(Session, Session.id == Lap.session_id)
                .join(Meeting, Meeting.id == Session.meeting_id)
                .join(Season, Season.id == Meeting.season_id)
                .where(Season.year == season)
            )
        ).scalar_one()
    )

    latest_round = (
        await connection.execute(
            select(Meeting.round_number)
            .join(Season, Season.id == Meeting.season_id)
            .join(Session, Session.meeting_id == Meeting.id)
            .where(Season.year == season)
            .where(Session.session_type == SessionType.RACE)
            .where(Session.ingested_at.is_not(None))
            .order_by(Meeting.round_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    latest_race: RaceSummary | None = None
    podium: list[ClassificationRow] = []
    if latest_round is not None:
        detail = await get_race(connection, season, latest_round)
        if detail is not None:
            latest_race = RaceSummary(**detail.model_dump(include=set(RaceSummary.model_fields)))
            session_id = await _resolve_session(connection, season, latest_round)
            if session_id is not None:
                podium = (await _classification(connection, session_id))[:3]

    return DashboardData(
        season=season,
        rounds_ingested=rounds_ingested,
        rounds_on_calendar=rounds_on_calendar,
        laps_stored=laps_stored,
        latest_race=latest_race,
        latest_podium=podium,
    )


class DashboardData:
    """Plain carrier, converted to the wire model by the route."""

    def __init__(
        self,
        season: int,
        rounds_ingested: int,
        rounds_on_calendar: int,
        laps_stored: int,
        latest_race: RaceSummary | None,
        latest_podium: list[ClassificationRow],
    ) -> None:
        self.season = season
        self.rounds_ingested = rounds_ingested
        self.rounds_on_calendar = rounds_on_calendar
        self.laps_stored = laps_stored
        self.latest_race = latest_race
        self.latest_podium = latest_podium
