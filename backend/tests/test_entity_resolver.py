"""Entity resolution: questions become sessions, or a question back. No network.

"Today" is fixed at 2026-09-25: the 2026 Spanish GP (13 Sep) is the latest
race and the Azerbaijan GP (26 Sep) the next.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.agent.entities import (
    Intent,
    Resolution,
    ResolvedEntities,
    ResolvedSession,
)
from app.agent.entity_resolver import WHICH_RACE, CalendarUnavailableError, EntityResolver
from app.agent.mentions import SCHEMA, Mentions, parse_mentions
from app.db.models.enums import SessionType
from app.ingestion.base import RawEvent
from app.llm import Completion, JsonSchema, LLMInvalidResponseError, Message

TODAY = dt.date(2026, 9, 25)
CONVENTIONAL = (
    SessionType.PRACTICE_1,
    SessionType.PRACTICE_2,
    SessionType.PRACTICE_3,
    SessionType.QUALIFYING,
    SessionType.RACE,
)
SPRINT = (
    SessionType.PRACTICE_1,
    SessionType.SPRINT_QUALIFYING,
    SessionType.SPRINT,
    SessionType.QUALIFYING,
    SessionType.RACE,
)


def event(
    season: int,
    round_number: int,
    name: str,
    location: str,
    day: tuple[int, int],
    sessions: tuple[SessionType, ...] = CONVENTIONAL,
) -> RawEvent:
    return RawEvent(
        season=season,
        round_number=round_number,
        event_name=name,
        official_name=None,
        event_date=dt.date(season, *day),
        country=None,
        location=location,
        event_format=None,
        sessions=sessions,
    )


CALENDARS: dict[int, tuple[RawEvent, ...]] = {
    2020: (
        event(2020, 4, "British Grand Prix", "Silverstone", (8, 2)),
        event(2020, 5, "70th Anniversary Grand Prix", "Silverstone", (8, 9)),
    ),
    2023: (event(2023, 14, "Italian Grand Prix", "Monza", (9, 3)),),
    2024: (
        event(2024, 1, "Bahrain Grand Prix", "Sakhir", (3, 2)),
        event(2024, 11, "Austrian Grand Prix", "Spielberg", (6, 30), SPRINT),
        event(2024, 12, "British Grand Prix", "Silverstone", (7, 7)),
        event(2024, 16, "Italian Grand Prix", "Monza", (9, 1)),
        event(2024, 24, "Abu Dhabi Grand Prix", "Yas Island", (12, 8)),
    ),
    2025: (
        event(2025, 16, "Italian Grand Prix", "Monza", (9, 7)),
        event(2025, 24, "Abu Dhabi Grand Prix", "Yas Island", (12, 7)),
    ),
    2026: (
        event(2026, 1, "Australian Grand Prix", "Melbourne", (3, 8)),
        event(2026, 13, "Italian Grand Prix", "Monza", (9, 6)),
        event(2026, 14, "Spanish Grand Prix", "Madrid", (9, 13)),
        event(2026, 15, "Azerbaijan Grand Prix", "Baku", (9, 26)),
    ),
}


class FakeCalendar:
    def __init__(self, calendars: dict[int, tuple[RawEvent, ...]] = CALENDARS) -> None:
        self._calendars = calendars
        self.requested: list[int] = []

    async def get(self, season: int) -> tuple[RawEvent, ...]:
        self.requested.append(season)
        return self._calendars.get(season, ())


class FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[tuple[list[Message], JsonSchema | None]] = []

    @property
    def model(self) -> str:
        return "fake"

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Completion:
        self.calls.append((messages, schema))
        return Completion(text=self._text, model="fake")


def resolver(
    today: dt.date = TODAY, calendar: FakeCalendar | None = None, llm: FakeLLM | None = None
) -> EntityResolver:
    return EntityResolver(llm or FakeLLM("{}"), calendar or FakeCalendar(), today=lambda: today)


def mentions(intent: str = "session", **fields: Any) -> Mentions:
    return parse_mentions({"intent": intent, **fields})


def target(**fields: Any) -> dict[str, Any]:
    return fields


async def resolve(
    found: Mentions, previous: ResolvedEntities | None = None, **kwargs: Any
) -> Resolution:
    return await resolver(**kwargs).resolve_mentions(found, previous)


def only_session(resolution: Resolution) -> ResolvedSession:
    assert resolution.entities is not None, resolution.clarifying_question
    (session,) = resolution.entities.sessions
    return session


class TestExplicitRace:
    async def test_year_and_race_resolve_to_the_round(self) -> None:
        resolution = await resolve(mentions(targets=[target(race="Monza", year=2024)]))

        session = only_session(resolution)
        assert (session.year, session.round_number) == (2024, 16)
        assert session.grand_prix == "Italian Grand Prix"
        assert session.session_type is SessionType.RACE
        assert session.session_inferred
        assert not session.year_inferred

    async def test_named_session_is_kept(self) -> None:
        resolution = await resolve(
            mentions(targets=[target(race="Silverstone", year=2024, session="qualifying")])
        )

        session = only_session(resolution)
        assert session.session_type is SessionType.QUALIFYING
        assert not session.session_inferred

    async def test_year_stated_for_the_whole_question_applies_to_each_race(self) -> None:
        resolution = await resolve(
            mentions(year=2024, targets=[target(race="Monza"), target(race="Silverstone")])
        )

        assert resolution.entities is not None
        assert [s.round_number for s in resolution.entities.sessions] == [16, 12]

    async def test_the_same_session_twice_is_resolved_once(self) -> None:
        resolution = await resolve(
            mentions(targets=[target(race="Monza", year=2024), target(race="Italy", year=2024)])
        )

        only_session(resolution)

    async def test_drivers_and_constructors_are_passed_through(self) -> None:
        resolution = await resolve(
            mentions(
                targets=[target(race="Monza", year=2024)],
                drivers=["Norris", " Leclerc ", "Norris"],
                constructors=["Ferrari"],
            )
        )

        assert resolution.entities is not None
        assert resolution.entities.drivers == ("Norris", "Leclerc")
        assert resolution.entities.constructors == ("Ferrari",)


class TestRelativeReferences:
    async def test_last_race_is_the_most_recent_one_run(self) -> None:
        session = only_session(await resolve(mentions(targets=[target(reference="latest")])))

        assert (session.year, session.round_number) == (2026, 14)
        assert session.year_inferred

    async def test_next_race_is_the_first_one_not_yet_run(self) -> None:
        session = only_session(await resolve(mentions(targets=[target(reference="next")])))

        assert (session.year, session.round_number) == (2026, 15)

    async def test_on_race_day_the_last_race_is_still_the_previous_one(self) -> None:
        # Seen live: on race morning, "who won the last race?" started a
        # fetch for today's race, which had no results yet and failed.
        race_day = dt.date(2026, 9, 26)

        last = only_session(
            await resolve(mentions(targets=[target(reference="latest")]), today=race_day)
        )
        upcoming = only_session(
            await resolve(mentions(targets=[target(reference="next")]), today=race_day)
        )

        assert last.round_number == 14
        assert upcoming.round_number == 15

    async def test_last_race_before_the_season_starts_is_last_seasons_finale(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(reference="latest")]), today=dt.date(2026, 2, 1))
        )

        assert (session.year, session.round_number) == (2025, 24)

    async def test_this_season_added_to_last_race_is_still_treated_as_inferred(self) -> None:
        # Seen live: the model adds relative_year "current" to "the last race".
        found = mentions(targets=[target(reference="latest", relative_year="current")])

        session = only_session(await resolve(found, today=dt.date(2026, 2, 1)))

        assert (session.year, session.round_number) == (2025, 24)
        assert session.year_inferred

    async def test_last_race_of_last_season_is_its_finale(self) -> None:
        found = mentions(targets=[target(reference="latest", relative_year="previous")])

        session = only_session(await resolve(found))

        assert (session.year, session.round_number) == (2025, 24)
        assert not session.year_inferred

    async def test_last_race_of_a_stated_season_is_its_finale(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(reference="latest", year=2024)]))
        )

        assert (session.year, session.round_number) == (2024, 24)
        assert not session.year_inferred

    async def test_first_race_of_a_season_is_round_one(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(reference="first", year=2024)]))
        )

        assert session.round_number == 1

    async def test_last_year_is_worked_out_from_today(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(race="Monza", relative_year="previous")]))
        )

        assert (session.year, session.round_number) == (2025, 16)

    async def test_this_year_is_the_current_season(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(race="Monza", relative_year="current")]))
        )

        assert (session.year, session.round_number) == (2026, 13)

    async def test_next_race_after_the_finale_is_next_seasons_opener(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(reference="next")]), today=dt.date(2025, 12, 20))
        )

        assert (session.year, session.round_number) == (2026, 1)
        assert session.year_inferred

    async def test_next_race_with_next_calendar_unpublished_says_none_left(self) -> None:
        resolution = await resolve(
            mentions(targets=[target(reference="next")]), today=dt.date(2026, 12, 20)
        )

        assert resolution.clarifying_question == "There are no more races scheduled in 2026."

    async def test_no_next_race_after_the_finale(self) -> None:
        resolution = await resolve(mentions(targets=[target(reference="next", year=2024)]))

        assert resolution.clarifying_question == "There are no more races scheduled in 2024."

    async def test_a_stated_season_with_no_race_yet_says_so(self) -> None:
        resolution = await resolve(
            mentions(targets=[target(reference="latest", year=2026)]), today=dt.date(2026, 2, 1)
        )

        assert resolution.clarifying_question == "The 2026 season has not had a race yet."


class TestClarification:
    async def test_race_without_a_year_asks_which_year(self) -> None:
        resolution = await resolve(mentions(targets=[target(race="Silverstone")]))

        assert resolution.clarifying_question == "Which year's Silverstone do you mean?"

    async def test_two_events_at_one_venue_asks_which(self) -> None:
        resolution = await resolve(mentions(targets=[target(race="Silverstone", year=2020)]))

        assert resolution.clarifying_question == (
            'In 2020, "Silverstone" could mean the British Grand Prix or the '
            "70th Anniversary Grand Prix. Which one do you mean?"
        )

    async def test_no_race_at_all_asks_which_race(self) -> None:
        resolution = await resolve(mentions(drivers=["Norris"]))

        assert resolution.clarifying_question == WHICH_RACE

    async def test_unknown_race_asks_again(self) -> None:
        resolution = await resolve(mentions(targets=[target(race="Kyalami", year=2024)]))

        assert resolution.clarifying_question == (
            'I couldn\'t find "Kyalami" on the 2024 calendar. Which race do you mean?'
        )

    async def test_long_user_text_is_shortened_when_echoed(self) -> None:
        resolution = await resolve(mentions(targets=[target(race="x" * 500, year=2024)]))

        assert resolution.clarifying_question is not None
        assert len(resolution.clarifying_question) < 150

    async def test_session_the_weekend_did_not_have(self) -> None:
        resolution = await resolve(
            mentions(targets=[target(race="Monza", year=2024, session="sprint")])
        )

        assert resolution.clarifying_question == (
            "The 2024 Italian Grand Prix had no sprint. Did you mean the race?"
        )

    async def test_sprint_on_a_sprint_weekend_is_fine(self) -> None:
        session = only_session(
            await resolve(mentions(targets=[target(race="Austria", year=2024, session="sprint")]))
        )

        assert session.session_type is SessionType.SPRINT

    @pytest.mark.parametrize("year", [2010, 2028])
    async def test_seasons_outside_the_data_are_refused(self, year: int) -> None:
        resolution = await resolve(mentions(targets=[target(race="Monza", year=year)]))

        assert resolution.clarifying_question == (
            "I can look up seasons from 2018 to 2027. Which season do you mean?"
        )

    async def test_calendar_failure_is_an_error_not_a_question(self) -> None:
        with pytest.raises(CalendarUnavailableError):
            await resolve(
                mentions(targets=[target(race="Monza", year=2024)]),
                calendar=FakeCalendar({}),
            )


def previous_turn(**overrides: Any) -> ResolvedEntities:
    values: dict[str, Any] = {
        "intent": Intent.SESSION,
        "sessions": (
            ResolvedSession(
                year=2024,
                round_number=16,
                grand_prix="Italian Grand Prix",
                session_type=SessionType.RACE,
                event_date=dt.date(2024, 9, 1),
            ),
        ),
        "drivers": ("Norris",),
    }
    values.update(overrides)
    return ResolvedEntities(**values)


class TestFollowUps:
    async def test_new_driver_keeps_the_previous_race(self) -> None:
        resolution = await resolve(mentions(follow_up=True, drivers=["Leclerc"]), previous_turn())

        assert resolution.entities is not None
        assert resolution.entities.sessions == previous_turn().sessions
        assert resolution.entities.drivers == ("Leclerc",)

    async def test_other_session_keeps_the_weekend_and_drivers(self) -> None:
        resolution = await resolve(
            mentions(follow_up=True, targets=[target(session="qualifying")]), previous_turn()
        )

        session = only_session(resolution)
        assert (session.year, session.round_number) == (2024, 16)
        assert session.session_type is SessionType.QUALIFYING
        assert resolution.entities is not None
        assert resolution.entities.drivers == ("Norris",)

    async def test_other_session_for_several_earlier_races_keeps_each_race(self) -> None:
        both = (
            *previous_turn().sessions,
            ResolvedSession(2024, 12, "British Grand Prix", SessionType.RACE, dt.date(2024, 7, 7)),
        )
        found = mentions(
            follow_up=True,
            targets=[target(session="qualifying"), target(session="qualifying")],
        )

        resolution = await resolve(found, previous_turn(sessions=both))

        assert resolution.entities is not None
        assert [(s.round_number, s.session_type) for s in resolution.entities.sessions] == [
            (16, SessionType.QUALIFYING),
            (12, SessionType.QUALIFYING),
        ]

    async def test_standings_follow_up_keeps_a_guessed_season_flagged(self) -> None:
        # Turn 1, pre-season: "how did the last race go?" -> 2025 finale, guessed.
        first = await resolve(
            mentions(targets=[target(reference="latest")]), today=dt.date(2026, 2, 1)
        )
        assert first.entities is not None

        second = await resolve(mentions("standings", follow_up=True), first.entities)

        assert second.entities is not None
        assert (second.entities.year, second.entities.year_inferred) == (2025, True)

    async def test_other_season_keeps_the_grand_prix(self) -> None:
        resolution = await resolve(mentions(follow_up=True, year=2023), previous_turn())

        session = only_session(resolution)
        assert (session.year, session.round_number) == (2023, 14)

    async def test_other_race_without_a_year_keeps_the_season(self) -> None:
        resolution = await resolve(
            mentions(follow_up=True, targets=[target(race="Silverstone")]), previous_turn()
        )

        session = only_session(resolution)
        assert (session.year, session.round_number) == (2024, 12)

    async def test_previous_turn_is_ignored_unless_this_is_a_follow_up(self) -> None:
        resolution = await resolve(mentions(drivers=["Leclerc"]), previous_turn())

        assert resolution.clarifying_question == WHICH_RACE

    async def test_follow_up_with_no_earlier_race_asks(self) -> None:
        previous = previous_turn(intent=Intent.STANDINGS, sessions=(), year=2024)

        resolution = await resolve(mentions(follow_up=True, drivers=["Leclerc"]), previous)

        assert resolution.clarifying_question == WHICH_RACE


class TestSeasonScopedQuestions:
    async def test_standings_without_a_year_assume_this_season_and_say_so(self) -> None:
        resolution = await resolve(mentions("standings"))

        assert resolution.entities == ResolvedEntities(
            intent=Intent.STANDINGS, year=2026, year_inferred=True
        )

    async def test_standings_for_last_year(self) -> None:
        resolution = await resolve(mentions("standings", relative_year="previous"))

        assert resolution.entities is not None
        assert (resolution.entities.year, resolution.entities.year_inferred) == (2025, False)

    async def test_standings_year_given_on_a_target_counts(self) -> None:
        resolution = await resolve(mentions("standings", targets=[target(year=2021)]))

        assert resolution.entities is not None
        assert resolution.entities.year == 2021

    async def test_standings_follow_up_inherits_the_season(self) -> None:
        resolution = await resolve(mentions("standings", follow_up=True), previous_turn())

        assert resolution.entities is not None
        assert (resolution.entities.year, resolution.entities.year_inferred) == (2024, False)

    async def test_season_wide_question_keeps_its_year_and_needs_no_calendar(self) -> None:
        calendar = FakeCalendar()

        resolution = await resolve(mentions("season", year=2024), calendar=calendar)

        assert resolution.entities is not None
        assert resolution.entities.intent is Intent.SEASON
        assert resolution.entities.year == 2024
        assert calendar.requested == []

    async def test_unsupported_question_resolves_to_nothing(self) -> None:
        resolution = await resolve(mentions("unsupported"))

        assert resolution.entities == ResolvedEntities(intent=Intent.UNSUPPORTED)


class TestResolution:
    def test_holds_exactly_one_outcome(self) -> None:
        with pytest.raises(ValueError):
            Resolution()
        with pytest.raises(ValueError):
            Resolution(ResolvedEntities(Intent.SESSION), "which?")

    def test_needs_clarification_only_with_a_question(self) -> None:
        assert Resolution.ask("which?").needs_clarification
        assert not Resolution.of(ResolvedEntities(Intent.SESSION)).needs_clarification


class TestEndToEnd:
    async def test_question_goes_to_the_model_with_the_schema(self) -> None:
        llm = FakeLLM(
            '{"intent": "session", "year": null, "relative_year": null, '
            '"targets": [{"race": "Monza", "reference": null, "year": 2024, '
            '"relative_year": null, "session": null}], "drivers": ["Norris"], '
            '"constructors": [], "follow_up": false}'
        )

        resolution = await resolver(llm=llm).resolve("Where did Norris finish at Monza 2024?")

        session = only_session(resolution)
        assert session.round_number == 16
        messages, schema = llm.calls[0]
        assert schema is SCHEMA
        assert messages[0].role == "system"
        assert messages[1].content == "Question: Where did Norris finish at Monza 2024?"

    async def test_previous_turn_is_summarised_for_the_model(self) -> None:
        llm = FakeLLM('{"intent": "session", "follow_up": true, "drivers": ["Leclerc"]}')

        await resolver(llm=llm).resolve("and Leclerc?", previous_turn())

        messages, _ = llm.calls[0]
        assert messages[1].content == (
            "Previous question was about: 2024 Italian Grand Prix race; drivers Norris\n"
            "Question: and Leclerc?"
        )

    @pytest.mark.parametrize(
        "text", ['{"intent": "gossip"}', '{"intent": "session", "targets": "Monza"}', "[]"]
    )
    async def test_output_outside_the_schema_is_rejected(self, text: str) -> None:
        with pytest.raises(LLMInvalidResponseError):
            await resolver(llm=FakeLLM(text)).resolve("Who won?")


class TestSchema:
    def test_schema_lists_exactly_the_model_fields(self) -> None:
        properties = SCHEMA.schema["properties"]
        target_properties = properties["targets"]["items"]["properties"]

        assert set(properties) == set(Mentions.model_fields)
        assert SCHEMA.schema["required"] == list(properties)
        assert set(target_properties) == {"race", "reference", "year", "relative_year", "session"}

    def test_every_object_is_closed_for_strict_mode(self) -> None:
        assert SCHEMA.strict
        assert SCHEMA.schema["additionalProperties"] is False
        assert SCHEMA.schema["properties"]["targets"]["items"]["additionalProperties"] is False

    def test_session_enum_matches_the_database(self) -> None:
        session = SCHEMA.schema["properties"]["targets"]["items"]["properties"]["session"]

        assert session["enum"] == [*(s.value for s in SessionType), None]

    def test_targets_and_names_are_capped(self) -> None:
        found = mentions(
            targets=[target(race=f"r{i}") for i in range(10)],
            drivers=[f"d{i}" for i in range(10)],
        )

        assert len(found.targets) == 4
        assert len(found.drivers) == 6

    def test_a_season_question_that_names_a_race_is_about_that_session(self) -> None:
        found = mentions("season", year=2024, targets=[target(reference="first", year=2024)])

        assert found.intent is Intent.SESSION

    def test_a_season_question_with_only_a_year_stays_season_wide(self) -> None:
        assert mentions("season", targets=[target(year=2024)]).intent is Intent.SEASON

    def test_a_named_race_drops_a_conflicting_reference(self) -> None:
        found = mentions(targets=[target(race="Hungarian Grand Prix", reference="latest")])

        assert found.targets[0].reference is None
        assert found.targets[0].race == "Hungarian Grand Prix"

    def test_blank_race_counts_as_none(self) -> None:
        assert mentions(targets=[target(race="  ")]).targets[0].race is None
