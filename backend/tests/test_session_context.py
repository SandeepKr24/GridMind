"""Pinning a question to session, driver and team ids."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.agent.entities import Intent, ResolvedEntities, ResolvedSession
from app.agent.session_context import (
    ContextProblem,
    Entrant,
    SessionContext,
    StoredSession,
    _load_one,
    build_context,
)
from app.db.models.enums import SessionType
from app.ingestion.normalizer import SessionWriter
from tests.conftest_db import TEST_SEASON, connection, database, sample_session  # noqa: F401

SPA = ResolvedSession(2024, 14, "Belgian Grand Prix", SessionType.RACE, dt.date(2024, 7, 28))
HUNGARY = ResolvedSession(2024, 13, "Hungarian Grand Prix", SessionType.RACE, None)


def entrant(
    driver_id: int, full: str, code: str, team_id: int, team: str, first: str | None = None
) -> Entrant:
    first_name, _, last_name = full.partition(" ")
    return Entrant(driver_id, code, first or first_name, last_name, full, team_id, team)


GRID = (
    entrant(1, "Max Verstappen", "VER", 10, "Red Bull Racing"),
    entrant(4, "Lando Norris", "NOR", 11, "McLaren"),
    entrant(16, "Charles Leclerc", "LEC", 12, "Ferrari"),
    entrant(55, "Carlos Sainz", "SAI", 12, "Ferrari"),
    entrant(22, "Yuki Tsunoda", "TSU", 13, "RB"),
    entrant(12, "Andrea Kimi Antonelli", "ANT", 14, "Mercedes", first="Andrea Kimi"),
    entrant(63, "George Russell", "RUS", 14, "Mercedes"),
)


class FakeDirectory:
    def __init__(self, stored: dict[tuple[int, int, SessionType], StoredSession]) -> None:
        self._stored = stored

    async def load(self, sessions: Sequence[ResolvedSession]) -> tuple[StoredSession, ...]:
        return tuple(self._stored[s.key] for s in sessions if s.key in self._stored)


def directory(*sessions: ResolvedSession) -> FakeDirectory:
    return FakeDirectory({s.key: StoredSession(100 + i, s, GRID) for i, s in enumerate(sessions)})


async def context_for(
    drivers: tuple[str, ...] = (),
    constructors: tuple[str, ...] = (),
    sessions: tuple[ResolvedSession, ...] = (SPA,),
    stored: tuple[ResolvedSession, ...] = (SPA,),
) -> SessionContext | ContextProblem:
    entities = ResolvedEntities(
        Intent.SESSION, sessions=sessions, drivers=drivers, constructors=constructors
    )
    return await build_context(directory(*stored), entities)


def ok(context: SessionContext | ContextProblem) -> SessionContext:
    assert isinstance(context, SessionContext), context
    return context


class TestSessions:
    async def test_each_resolved_session_gets_its_id(self) -> None:
        context = ok(await context_for(sessions=(SPA, HUNGARY), stored=(SPA, HUNGARY)))

        assert [s.session_id for s in context.sessions] == [100, 101]

    async def test_a_session_not_stored_is_reported_not_guessed(self) -> None:
        problem = await context_for(sessions=(SPA, HUNGARY), stored=(SPA,))

        assert problem == ContextProblem(
            "The data for the 2024 Hungarian Grand Prix race is not stored yet."
        )


class TestDrivers:
    @pytest.mark.parametrize(
        ("name", "driver_id"),
        [
            ("Norris", 4),
            ("norris", 4),
            ("NOR", 4),
            ("Lando Norris", 4),
            ("Leclerc", 16),
            ("Kimi", 12),
            ("Antonelli", 12),
            ("Verstap", 1),
        ],
    )
    async def test_names_codes_and_partials_match_one_entrant(
        self, name: str, driver_id: int
    ) -> None:
        context = ok(await context_for(drivers=(name,)))

        assert [d.id for d in context.drivers] == [driver_id]
        assert context.drivers[0].asked_as == name

    async def test_label_carries_the_code(self) -> None:
        context = ok(await context_for(drivers=("Norris",)))

        assert context.drivers[0].label == "Lando Norris (NOR)"

    async def test_someone_not_in_the_session_is_a_clear_problem(self) -> None:
        problem = await context_for(drivers=("Schumacher",))

        assert problem == ContextProblem(
            'No driver called "Schumacher" took part in the 2024 Belgian Grand Prix race.'
        )

    async def test_a_surname_two_entrants_share_asks_which(self) -> None:
        stored = StoredSession(
            1,
            SPA,
            (
                entrant(1, "Max Verstappen", "VER", 10, "Red Bull Racing"),
                entrant(2, "Jos Verstappen", "JOS", 15, "Minardi"),
            ),
        )
        entities = ResolvedEntities(Intent.SESSION, sessions=(SPA,), drivers=("Verstappen",))

        problem = await build_context(FakeDirectory({SPA.key: stored}), entities)

        assert problem == ContextProblem(
            '"Verstappen" could mean Max Verstappen or Jos Verstappen. Which driver do you mean?'
        )

    async def test_a_fragment_too_short_to_trust_matches_nobody(self) -> None:
        # "an" is inside several names; two letters are not an identity.
        problem = await context_for(drivers=("an",))

        assert isinstance(problem, ContextProblem)
        assert problem.message.startswith('No driver called "an"')

    async def test_several_drivers_resolve_in_order(self) -> None:
        context = ok(await context_for(drivers=("Leclerc", "Norris")))

        assert [d.id for d in context.drivers] == [16, 4]


class TestTeams:
    @pytest.mark.parametrize(
        ("name", "team_id"), [("Ferrari", 12), ("Red Bull", 10), ("mclaren", 11), ("RB", 13)]
    )
    async def test_team_names_match(self, name: str, team_id: int) -> None:
        context = ok(await context_for(constructors=(name,)))

        assert [c.id for c in context.constructors] == [team_id]

    async def test_an_unknown_team_is_a_clear_problem(self) -> None:
        problem = await context_for(constructors=("Brawn",))

        assert problem == ContextProblem(
            'No team called "Brawn" took part in the 2024 Belgian Grand Prix race.'
        )

    async def test_a_name_inside_two_teams_asks_which(self) -> None:
        stored = StoredSession(
            1,
            SPA,
            (
                entrant(1, "Max Verstappen", "VER", 10, "Red Bull Racing"),
                entrant(22, "Yuki Tsunoda", "TSU", 13, "Racing Bulls"),
            ),
        )
        entities = ResolvedEntities(Intent.SESSION, sessions=(SPA,), constructors=("racing",))

        problem = await build_context(FakeDirectory({SPA.key: stored}), entities)

        assert problem == ContextProblem(
            '"racing" could mean Red Bull Racing or Racing Bulls. Which team do you mean?'
        )


class TestLoadingFromPostgres:
    async def test_a_stored_session_loads_with_its_entrants(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        await SessionWriter(connection).store(sample_session())
        wanted = ResolvedSession(TEST_SEASON, 1, "Test Grand Prix", SessionType.RACE, None)

        stored = await _load_one(connection, wanted)

        assert stored is not None
        assert {e.full_name for e in stored.entrants} == {"Max Verstappen", "Lando Norris"}
        assert {e.constructor_name for e in stored.entrants} == {"Red Bull Racing", "McLaren"}

    async def test_a_session_not_stored_loads_as_none(
        self,
        connection: AsyncConnection,  # noqa: F811
    ) -> None:
        wanted = ResolvedSession(TEST_SEASON, 1, "Test Grand Prix", SessionType.QUALIFYING, None)

        assert await _load_one(connection, wanted) is None
