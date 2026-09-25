"""Pin a question to database ids before any SQL is written.

The resolver knows which sessions a question is about; this module looks up
their `session_id`s and matches the names the user mentioned against the
drivers and teams who actually took part. The SQL model is then handed
constants (`session_id = 57`, `driver_id = 4`) instead of names to join on,
which makes its SQL shorter, its prompt smaller and its mistakes rarer.

Matching against the session's entrants, rather than every driver ever
stored, is what makes a surname unambiguous: "Schumacher" in 2021 is Mick.
A name nobody in the session answers to becomes a clarifying question before
a single token is spent on SQL.

Runs on the read-only role, like everything on the agent's path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.agent.entities import ResolvedEntities, ResolvedSession
from app.agent.race_matcher import normalise
from app.db.database import Database
from app.db.models import Constructor, Driver, Meeting, Season, Session, SessionResult


@dataclass(frozen=True, slots=True)
class Entrant:
    driver_id: int
    code: str | None
    first_name: str | None
    last_name: str | None
    full_name: str
    constructor_id: int | None
    constructor_name: str | None


@dataclass(frozen=True, slots=True)
class StoredSession:
    session_id: int
    session: ResolvedSession
    entrants: tuple[Entrant, ...]


@dataclass(frozen=True, slots=True)
class NamedId:
    #: What the user called them.
    asked_as: str
    id: int
    label: str


@dataclass(frozen=True, slots=True)
class SessionContext:
    sessions: tuple[StoredSession, ...]
    drivers: tuple[NamedId, ...] = ()
    constructors: tuple[NamedId, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextProblem:
    """Why the question cannot be pinned down; shown to the user as-is."""

    message: str


class SessionDirectory(Protocol):
    async def load(self, sessions: Sequence[ResolvedSession]) -> tuple[StoredSession, ...]: ...


def _driver_keys(entrant: Entrant) -> set[str]:
    keys = {normalise(entrant.full_name)}
    for part in (entrant.last_name, entrant.code, entrant.first_name):
        if part:
            keys.add(normalise(part))
    return keys


def _match_driver(name: str, entrants: Sequence[Entrant]) -> list[Entrant]:
    wanted = normalise(name)
    exact = [e for e in entrants if wanted in _driver_keys(e)]
    if exact:
        return exact
    # "Verstap" or "Sainz Jr": a partial match within the one session only.
    return [e for e in entrants if len(wanted) >= 3 and wanted in normalise(e.full_name)]


def _match_team(name: str, entrants: Sequence[Entrant]) -> dict[int, str]:
    wanted = normalise(name)
    teams = {e.constructor_id: e.constructor_name for e in entrants if e.constructor_id}
    return {
        team_id: team_name or ""
        for team_id, team_name in teams.items()
        if team_name and (wanted in normalise(team_name) or normalise(team_name) in wanted)
    }


def _describe(stored: Sequence[StoredSession]) -> str:
    return " and ".join(f"the {s.session.describe()}" for s in stored)


def _resolve_drivers(
    names: Sequence[str], stored: Sequence[StoredSession]
) -> tuple[NamedId, ...] | ContextProblem:
    entrants = {e.driver_id: e for s in stored for e in s.entrants}.values()
    found: list[NamedId] = []
    for name in names:
        matches = {e.driver_id: e for e in _match_driver(name, list(entrants))}
        if not matches:
            return ContextProblem(f'No driver called "{name}" took part in {_describe(stored)}.')
        if len(matches) > 1:
            options = " or ".join(e.full_name for e in matches.values())
            return ContextProblem(f'"{name}" could mean {options}. Which driver do you mean?')
        (entrant,) = matches.values()
        label = entrant.full_name + (f" ({entrant.code})" if entrant.code else "")
        found.append(NamedId(name, entrant.driver_id, label))
    return tuple(found)


def _resolve_teams(
    names: Sequence[str], stored: Sequence[StoredSession]
) -> tuple[NamedId, ...] | ContextProblem:
    entrants = [e for s in stored for e in s.entrants]
    found: list[NamedId] = []
    for name in names:
        matches = _match_team(name, entrants)
        if not matches:
            return ContextProblem(f'No team called "{name}" took part in {_describe(stored)}.')
        if len(matches) > 1:
            options = " or ".join(matches.values())
            return ContextProblem(f'"{name}" could mean {options}. Which team do you mean?')
        ((team_id, team_name),) = matches.items()
        found.append(NamedId(name, team_id, team_name))
    return tuple(found)


async def build_context(
    directory: SessionDirectory, entities: ResolvedEntities
) -> SessionContext | ContextProblem:
    """Ids for everything the question names, or the reason there are none.

    Expects the ingestion gate to have passed: every session is stored.
    """
    stored = await directory.load(entities.sessions)
    if len(stored) != len(entities.sessions):
        missing = {s.key for s in entities.sessions} - {s.session.key for s in stored}
        described = [s.describe() for s in entities.sessions if s.key in missing]
        return ContextProblem(f"The data for the {', '.join(described)} is not stored yet.")

    drivers = _resolve_drivers(entities.drivers, stored)
    if isinstance(drivers, ContextProblem):
        return drivers
    teams = _resolve_teams(entities.constructors, stored)
    if isinstance(teams, ContextProblem):
        return teams
    return SessionContext(stored, drivers, teams)


class PostgresSessionDirectory:
    """Stored sessions and their entrants, read on the read-only role."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self, sessions: Sequence[ResolvedSession]) -> tuple[StoredSession, ...]:
        async with self._db.connect(read_only=True) as connection:
            loaded = [await _load_one(connection, s) for s in sessions]
        return tuple(s for s in loaded if s is not None)


async def _load_one(connection: AsyncConnection, session: ResolvedSession) -> StoredSession | None:
    session_id = await connection.scalar(
        select(Session.id)
        .join(Meeting, Meeting.id == Session.meeting_id)
        .join(Season, Season.id == Meeting.season_id)
        .where(
            Season.year == session.year,
            Meeting.round_number == session.round_number,
            Session.session_type == session.session_type,
            Session.ingested_at.is_not(None),
        )
    )
    if session_id is None:
        return None
    rows = await connection.execute(
        select(
            Driver.id,
            Driver.driver_code,
            Driver.first_name,
            Driver.last_name,
            Driver.full_name,
            Constructor.id,
            Constructor.name,
        )
        .join(SessionResult, SessionResult.driver_id == Driver.id)
        .outerjoin(Constructor, Constructor.id == SessionResult.constructor_id)
        .where(SessionResult.session_id == session_id)
        .order_by(Driver.full_name)
    )
    entrants = tuple(Entrant(*row) for row in rows.all())
    return StoredSession(session_id, session, entrants)
