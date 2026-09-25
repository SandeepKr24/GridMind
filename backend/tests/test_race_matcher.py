"""Matching a user's name for a race against a real calendar."""

from __future__ import annotations

import datetime as dt

import pytest

from app.agent.race_matcher import match_events, normalise
from app.ingestion.base import RawEvent


def event(season: int, round_number: int, name: str, location: str, country: str) -> RawEvent:
    return RawEvent(
        season=season,
        round_number=round_number,
        event_name=name,
        official_name=None,
        event_date=dt.date(season, 1, 1) + dt.timedelta(weeks=round_number),
        country=country,
        location=location,
        event_format="conventional",
    )


# Names, locations and countries as FastF1 publishes them.
SEASON_2020 = (
    event(2020, 1, "Austrian Grand Prix", "Spielberg", "Austria"),
    event(2020, 2, "Styrian Grand Prix", "Spielberg", "Austria"),
    event(2020, 4, "British Grand Prix", "Silverstone", "Great Britain"),
    event(2020, 5, "70th Anniversary Grand Prix", "Silverstone", "Great Britain"),
    event(2020, 9, "Tuscan Grand Prix", "Mugello", "Italy"),
    event(2020, 8, "Italian Grand Prix", "Monza", "Italy"),
    event(2020, 13, "Emilia Romagna Grand Prix", "Imola", "Italy"),
    event(2020, 15, "Bahrain Grand Prix", "Sakhir", "Bahrain"),
    event(2020, 16, "Sakhir Grand Prix", "Sakhir", "Bahrain"),
    event(2020, 11, "Eifel Grand Prix", "Nürburgring", "Germany"),
    event(2020, 12, "Portuguese Grand Prix", "Portimão", "Portugal"),
)
SEASON_2018 = (
    event(2018, 7, "Canadian Grand Prix", "Montréal", "Canada"),
    event(2018, 16, "Russian Grand Prix", "Sochi", "Russia"),
    event(2018, 18, "United States Grand Prix", "Austin", "United States"),
    event(2018, 20, "Brazilian Grand Prix", "São Paulo", "Brazil"),
)
SEASON_2024 = (
    event(2024, 12, "British Grand Prix", "Silverstone", "United Kingdom"),
    event(2024, 14, "Belgian Grand Prix", "Spa-Francorchamps", "Belgium"),
    event(2024, 16, "Italian Grand Prix", "Monza", "Italy"),
    event(2024, 6, "Miami Grand Prix", "Miami", "United States"),
    event(2024, 19, "United States Grand Prix", "Austin", "United States"),
    event(2024, 21, "São Paulo Grand Prix", "São Paulo", "Brazil"),
    event(2024, 22, "Las Vegas Grand Prix", "Las Vegas", "United States"),
)
SEASON_2026 = (
    event(2026, 7, "Barcelona Grand Prix", "Barcelona", "Spain"),
    event(2026, 14, "Spanish Grand Prix", "Madrid", "Spain"),
)


def names(events: list[RawEvent]) -> list[str]:
    return sorted(e.event_name for e in events)


class TestNormalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("The British Grand Prix", "british"),
            ("Monza GP", "monza"),
            ("São Paulo", "sao paulo"),
            ("Spa-Francorchamps", "spa francorchamps"),
            ("  Circuit of the Americas ", "americas"),
            ("F1 Grand Prix", ""),
        ],
    )
    def test_strips_case_accents_punctuation_and_filler(self, raw: str, expected: str) -> None:
        assert normalise(raw) == expected


class TestMatchEvents:
    @pytest.mark.parametrize(
        ("query", "season", "expected"),
        [
            ("British Grand Prix", SEASON_2024, "British Grand Prix"),
            ("Silverstone", SEASON_2024, "British Grand Prix"),
            ("Monza", SEASON_2024, "Italian Grand Prix"),
            ("Spa", SEASON_2024, "Belgian Grand Prix"),
            ("Interlagos", SEASON_2024, "São Paulo Grand Prix"),
            ("Brazil", SEASON_2024, "São Paulo Grand Prix"),
            ("Interlagos", SEASON_2018, "Brazilian Grand Prix"),
            ("COTA", SEASON_2024, "United States Grand Prix"),
            ("Circuit of the Americas", SEASON_2024, "United States Grand Prix"),
            ("Vegas", SEASON_2024, "Las Vegas Grand Prix"),
            ("Montreal", SEASON_2018, "Canadian Grand Prix"),
            ("Imola", SEASON_2020, "Emilia Romagna Grand Prix"),
            ("Mugello", SEASON_2020, "Tuscan Grand Prix"),
            ("Nurburgring", SEASON_2020, "Eifel Grand Prix"),
            ("Portimao", SEASON_2020, "Portuguese Grand Prix"),
            ("Styria", SEASON_2020, "Styrian Grand Prix"),
            ("70th Anniversary", SEASON_2020, "70th Anniversary Grand Prix"),
            ("Spanish GP", SEASON_2026, "Spanish Grand Prix"),
            ("Madrid", SEASON_2026, "Spanish Grand Prix"),
            ("Catalunya", SEASON_2026, "Barcelona Grand Prix"),
            ("Sochi", SEASON_2018, "Russian Grand Prix"),
        ],
    )
    def test_finds_the_one_event_meant(
        self, query: str, season: tuple[RawEvent, ...], expected: str
    ) -> None:
        assert names(match_events(query, season)) == [expected]

    def test_an_events_own_name_beats_a_shared_venue(self) -> None:
        # Both 2020 Sakhir races ran at Sakhir; the name picks one.
        assert names(match_events("Sakhir", SEASON_2020)) == ["Sakhir Grand Prix"]
        assert names(match_events("Bahrain", SEASON_2020)) == ["Bahrain Grand Prix"]

    def test_an_alias_beats_the_country(self) -> None:
        # Italy hosted three rounds in 2020; "Italy" means the Italian GP.
        assert names(match_events("Italy", SEASON_2020)) == ["Italian Grand Prix"]
        assert names(match_events("Britain", SEASON_2020)) == ["British Grand Prix"]

    @pytest.mark.parametrize(
        ("query", "season", "expected"),
        [
            ("Silverstone", SEASON_2020, ["70th Anniversary Grand Prix", "British Grand Prix"]),
            ("Spielberg", SEASON_2020, ["Austrian Grand Prix", "Styrian Grand Prix"]),
            ("Spain", SEASON_2026, ["Barcelona Grand Prix", "Spanish Grand Prix"]),
        ],
    )
    def test_a_genuine_tie_returns_every_candidate(
        self, query: str, season: tuple[RawEvent, ...], expected: list[str]
    ) -> None:
        assert names(match_events(query, season)) == expected

    @pytest.mark.parametrize("query", ["Kyalami", "", "grand prix", "it"])
    def test_nothing_plausible_returns_nothing(self, query: str) -> None:
        assert match_events(query, SEASON_2024) == []

    def test_short_words_do_not_partially_match(self) -> None:
        # "us" is inside "russian"; that must not count.
        assert match_events("us", SEASON_2018) == [SEASON_2018[2]]
