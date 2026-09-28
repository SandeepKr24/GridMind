"""What the entity resolver decided a question is about.

These are plain values: the ingestion gate reads `sessions` to decide what to
fetch, the chat response echoes them as `resolved_entities`, and the
conversation store keeps them so a follow-up ("and Leclerc?") can inherit the
race. Nothing here touches the database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from app.db.models.enums import SessionType


class Intent(StrEnum):
    #: About specific sessions: one race, a qualifying, a practice.
    SESSION = "session"
    #: Needs many races of a season. The ingestion gate refuses these.
    SEASON = "season"
    #: Championship points and positions, served by the standings adapter.
    STANDINGS = "standings"
    #: Not a question about Formula 1 data.
    UNSUPPORTED = "unsupported"


SESSION_LABELS: dict[SessionType, str] = {
    SessionType.PRACTICE_1: "first practice",
    SessionType.PRACTICE_2: "second practice",
    SessionType.PRACTICE_3: "third practice",
    SessionType.QUALIFYING: "qualifying",
    SessionType.SPRINT_QUALIFYING: "sprint qualifying",
    SessionType.SPRINT: "sprint",
    SessionType.RACE: "race",
}


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    year: int
    round_number: int
    grand_prix: str
    session_type: SessionType
    event_date: dt.date | None
    #: The question did not state the year; it was worked out ("the last
    #: race") and the answer should say which season it assumed.
    year_inferred: bool = False
    #: No session was named, so the race was assumed.
    session_inferred: bool = False

    @property
    def key(self) -> tuple[int, int, SessionType]:
        return (self.year, self.round_number, self.session_type)

    def describe(self) -> str:
        return f"{self.year} {self.grand_prix} {SESSION_LABELS[self.session_type]}"


@dataclass(frozen=True, slots=True)
class ResolvedEntities:
    intent: Intent
    #: The season for season-wide and standings questions.
    year: int | None = None
    #: The year was not stated and the current season was assumed.
    year_inferred: bool = False
    sessions: tuple[ResolvedSession, ...] = ()
    #: Surnames as the model normalised them. They are matched against the
    #: session's entrants later, once that session's data is stored.
    drivers: tuple[str, ...] = ()
    constructors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Resolution:
    """Either entities to act on, or a question to put back to the user."""

    entities: ResolvedEntities | None = None
    clarifying_question: str | None = None
    #: The message rewritten to stand alone ("2026" after "Which year's
    #: Monza?" becomes the full question), when the model gave one.
    question: str | None = None

    def __post_init__(self) -> None:
        if (self.entities is None) == (self.clarifying_question is None):
            raise ValueError("a Resolution holds exactly one of entities or a question")

    @property
    def needs_clarification(self) -> bool:
        return self.clarifying_question is not None

    @classmethod
    def ask(cls, question: str) -> Resolution:
        return cls(clarifying_question=question)

    @classmethod
    def of(cls, entities: ResolvedEntities) -> Resolution:
        return cls(entities=entities)
