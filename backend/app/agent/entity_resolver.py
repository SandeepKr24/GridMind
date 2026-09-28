"""Turn a question into concrete sessions, or into a question back.

The model reports what the question mentions (`mentions.py`); everything
here is ordinary Python against the published calendar:

- "last year", "the last race" and "next race" are worked out from today's
  date, never by the model;
- a race name is matched against that season's real calendar
  (`race_matcher.py`);
- a race with no year, a name that matches two events, or a session the
  weekend did not have becomes a clarifying question, not a guess;
- a follow-up ("and Leclerc?", "what about qualifying?") inherits the
  previous turn's race;
- a reply to a clarifying question ("2026" after "Which year's Monza do you
  mean?") completes the question it answers.

Standings and season-wide questions need a season, not a race, and default to
the current one — flagged, so the answer can say it assumed.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import replace

from app.agent.conversations import Turn
from app.agent.entities import (
    SESSION_LABELS,
    Intent,
    Resolution,
    ResolvedEntities,
    ResolvedSession,
)
from app.agent.mentions import Mentions, RelativeYear, TargetMention, extract_mentions
from app.agent.race_matcher import match_events
from app.db.models.enums import SessionType
from app.ingestion.base import RawEvent
from app.ingestion.schedule import FIRST_SEASON, ScheduleSource
from app.llm import LLMProvider

WHICH_RACE = 'Which race do you mean? For example, "the 2024 British Grand Prix".'
#: User text is echoed back in clarifying questions; keep it short.
MAX_ECHO = 60
#: Joins a follow-up to the earlier question it leans on.
FOLLOW_UP = " Follow-up: "
#: "2023", "what about 2023?", "and in 2023", "how about the 2023 season".
_BARE_YEAR = re.compile(
    r"(?:and\s+|what\s+about\s+|how\s+about\s+)?(?:in\s+|for\s+)?(?:the\s+)?"
    r"((?:19|20)\d{2})(?:\s+(?:season|one|race|edition))?\s*[?.!]*",
    re.IGNORECASE,
)


class CalendarUnavailableError(RuntimeError):
    """The season's calendar could not be loaded, so no race can be resolved."""


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def _echo(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_ECHO else text[: MAX_ECHO - 1] + "…"


class EntityResolver:
    def __init__(
        self,
        llm: LLMProvider,
        calendar: ScheduleSource,
        *,
        today: Callable[[], dt.date] = _utc_today,
    ) -> None:
        self._llm = llm
        self._calendar = calendar
        self._today = today

    async def resolve(
        self,
        question: str,
        previous: ResolvedEntities | None = None,
        earlier: Turn | None = None,
    ) -> Resolution:
        mentions = await extract_mentions(self._llm, question, previous, earlier)
        mentions = _bare_year_follow_up(question, mentions, previous, earlier)
        resolution = await self.resolve_mentions(mentions, previous)
        return replace(resolution, question=_standalone(question, mentions, earlier))

    async def resolve_mentions(
        self, mentions: Mentions, previous: ResolvedEntities | None = None
    ) -> Resolution:
        # Earlier turns only count when the model says this one leans on them.
        context = previous if mentions.follow_up else None
        if mentions.intent is Intent.UNSUPPORTED and context and _names_anything(mentions):
            # Seen live: "what about 2023" after a Monza question came back
            # unsupported, with the year and follow_up set. Alone it says
            # nothing about F1; as a follow-up it asks the same thing again.
            mentions = mentions.model_copy(update={"intent": context.intent})
        base = ResolvedEntities(
            intent=mentions.intent,
            drivers=mentions.drivers or (context.drivers if context else ()),
            constructors=mentions.constructors or (context.constructors if context else ()),
        )
        if mentions.intent is Intent.UNSUPPORTED:
            return Resolution.of(base)
        if mentions.intent in (Intent.SEASON, Intent.STANDINGS):
            year, inferred = self._season_year(mentions, context)
            return Resolution.of(replace(base, year=year, year_inferred=inferred))
        return await self._resolve_sessions(mentions, context, base)

    def _stated_year(self, year: int | None, relative: RelativeYear | None) -> int | None:
        if year is not None:
            return year
        if relative == "current":
            return self._today().year
        if relative == "previous":
            return self._today().year - 1
        return None

    def _season_year(
        self, mentions: Mentions, context: ResolvedEntities | None
    ) -> tuple[int, bool]:
        stated = self._stated_year(mentions.year, mentions.relative_year)
        if stated is None:
            stated = next((t.year for t in mentions.targets if t.year is not None), None)
        if stated is not None:
            return stated, False
        if context is not None:
            if context.year is not None:
                return context.year, context.year_inferred
            if context.sessions:
                # A guessed season stays a guess: the answer must still say so.
                first = context.sessions[0]
                return first.year, first.year_inferred
        return self._today().year, True

    async def _resolve_sessions(
        self, mentions: Mentions, context: ResolvedEntities | None, base: ResolvedEntities
    ) -> Resolution:
        earlier = context.sessions if context is not None else ()
        pairs: list[tuple[TargetMention, ResolvedSession | None]]
        if mentions.targets:
            # "Qualifying for both?" pairs each target with its own earlier
            # session; extra targets fall back to the first one.
            pairs = [
                (target, earlier[min(i, len(earlier) - 1)] if earlier else None)
                for i, target in enumerate(mentions.targets)
            ]
        elif not earlier:
            return Resolution.ask(WHICH_RACE)
        elif self._stated_year(mentions.year, mentions.relative_year) is None:
            # "And Leclerc?": the same sessions, different people.
            return Resolution.of(replace(base, sessions=earlier))
        else:
            # "And in 2023?": the same sessions, another season.
            pairs = [(TargetMention(), session) for session in earlier]

        sessions: dict[tuple[int, int, SessionType], ResolvedSession] = {}
        for target, previous in pairs:
            outcome = await self._resolve_target(target, mentions, previous)
            if isinstance(outcome, str):
                return Resolution.ask(outcome)
            sessions.setdefault(outcome.key, outcome)
        return Resolution.of(replace(base, sessions=tuple(sessions.values())))

    async def _resolve_target(
        self, target: TargetMention, mentions: Mentions, previous: ResolvedSession | None
    ) -> ResolvedSession | str:
        stated = self._stated_year(target.year, target.relative_year) or self._stated_year(
            mentions.year, mentions.relative_year
        )
        if target.race is None and target.reference is None:
            if previous is None:
                return WHICH_RACE
            # "What about qualifying?" or "and in 2023?": same weekend, one change.
            target = TargetMention(
                race=previous.grand_prix, session=target.session or previous.session_type
            )
            stated = stated or previous.year

        year_inferred = False
        if target.reference is not None and target.year is None and mentions.year is None:
            # The model tends to add "current" to "the last race" unprompted.
            # Treat it as unstated, so a pre-season question still finds last
            # season's finale and the answer says which season it used.
            stated = self._stated_year(None, target.relative_year or mentions.relative_year)
            stated = None if stated == self._today().year else stated
        if stated is None:
            if target.reference is not None:
                stated, year_inferred = self._today().year, True
            elif previous is not None:
                stated = previous.year
            else:
                return f"Which year's {_echo(target.race or 'race')} do you mean?"

        latest = self._today().year + 1
        if not FIRST_SEASON <= stated <= latest:
            return (
                f"I can look up seasons from {FIRST_SEASON} to {latest}. Which season do you mean?"
            )

        picked = await self._pick_event(target, stated, year_inferred)
        if isinstance(picked, str):
            return picked
        return _session_of(picked, target.session, year_inferred=year_inferred)

    async def _pick_event(
        self, target: TargetMention, year: int, year_inferred: bool
    ) -> RawEvent | str:
        events = await self._events(year)
        if target.reference is not None:
            event = self._by_reference(target.reference, events)
            if event is None and year_inferred:
                # Pre-season, "the last race" is last season's finale; after the
                # finale, "the next race" is next season's opener.
                event = await self._across_seasons(target.reference, year)
            if event is not None:
                return event
            if target.reference == "next":
                return f"There are no more races scheduled in {year}."
            return f"The {year} season has not had a race yet."

        race = target.race or ""
        matches = match_events(race, events)
        if not matches:
            return (
                f'I couldn\'t find "{_echo(race)}" on the {year} calendar. Which race do you mean?'
            )
        if len(matches) > 1:
            names = " or ".join(f"the {e.event_name}" for e in matches)
            return f'In {year}, "{_echo(race)}" could mean {names}. Which one do you mean?'
        return matches[0]

    async def _across_seasons(self, reference: str, year: int) -> RawEvent | None:
        if reference == "first":
            return None
        neighbour = year - 1 if reference == "latest" else year + 1
        # Next season's calendar may not be published; that is "no race", not
        # an outage, so the calendar is asked directly rather than via _events.
        events = await self._calendar.get(neighbour)
        return self._by_reference(reference, events) if events else None

    async def _events(self, year: int) -> tuple[RawEvent, ...]:
        events = await self._calendar.get(year)
        if not events:
            raise CalendarUnavailableError(f"the {year} calendar could not be loaded")
        return events

    def _by_reference(self, reference: str, events: tuple[RawEvent, ...]) -> RawEvent | None:
        if reference == "first":
            return min(events, key=lambda e: e.round_number)
        today = self._today()
        dated = sorted(
            ((e.event_date, e.round_number, e) for e in events if e.event_date is not None),
            key=lambda item: item[:2],
        )
        # On race day, "the last race" is still the previous one: today's has
        # no classification until hours after the flag, and a fetch started
        # that morning can only fail. Today's race is "the next race" instead.
        if reference == "latest":
            return next((e for day, _, e in reversed(dated) if day < today), None)
        return next((e for day, _, e in dated if day >= today), None)


def _bare_year_follow_up(
    message: str, mentions: Mentions, previous: ResolvedEntities | None, earlier: Turn | None
) -> Mentions:
    """ "What about 2023?" after an answer asks the same thing of another season.

    Seen live after a Monza question: the model labelled it season-wide or
    unsupported, and mostly not a follow-up, so it was refused. A message that
    is only a year can mean nothing else. After a question back, though, a
    bare year is the reply to it ("Which year's Monza?" "2026"), which the
    model merges on its own.
    """
    match = _BARE_YEAR.fullmatch(message.strip())
    if match is None or previous is None or (earlier is not None and earlier.clarifying):
        return mentions
    return mentions.model_copy(
        update={
            "intent": previous.intent,
            "year": int(match[1]),
            "relative_year": None,
            "targets": (),
            "drivers": (),
            "constructors": (),
            "follow_up": True,
        }
    )


def _names_anything(mentions: Mentions) -> bool:
    """A year, race, session, driver or team: "what about pizza?" has none."""
    stated = mentions.year is not None or mentions.relative_year is not None
    in_targets = any(t != TargetMention() for t in mentions.targets)
    return stated or in_targets or bool(mentions.drivers or mentions.constructors)


def _standalone(message: str, mentions: Mentions, earlier: Turn | None) -> str | None:
    """The message as the SQL and answer models should read it, if not as sent.

    A reply to a clarifying question was merged by the model. A follow-up is
    joined to the question it leans on: "And Leclerc?" alone does not say
    what to look up about Leclerc. So is a reply the model left unmerged: it
    tends to leave "Hamilton" as it is after "No driver called Schumacher
    took part".
    """
    merged = mentions.question
    if merged is not None and merged.casefold() != " ".join(message.split()).casefold():
        return merged
    if not mentions.follow_up or earlier is None:
        return None
    if earlier.entities is None and not earlier.clarifying:
        return None  # a refusal: nothing to lean on
    # Chained follow-ups keep only the latest, so the text stays bounded.
    base = earlier.question.split(FOLLOW_UP)[0]
    return f"{base}{FOLLOW_UP}{' '.join(message.split())}"


def _session_of(
    event: RawEvent, requested: SessionType | None, *, year_inferred: bool
) -> ResolvedSession | str:
    session = requested or SessionType.RACE
    if event.sessions and session not in event.sessions:
        return (
            f"The {event.season} {event.event_name} had no {SESSION_LABELS[session]}. "
            "Did you mean the race?"
        )
    return ResolvedSession(
        year=event.season,
        round_number=event.round_number,
        grand_prix=event.event_name,
        session_type=session,
        event_date=event.event_date,
        year_inferred=year_inferred,
        session_inferred=requested is None,
    )
