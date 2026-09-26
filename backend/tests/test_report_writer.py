"""Report facts and the checks on what the model writes. No network, no database."""

from __future__ import annotations

import pytest

from app.api.schemas.race import (
    ClassificationRow,
    DriverStrategy,
    PitStopRow,
    PositionChange,
    RaceControlEventOut,
    RaceDetail,
    RaceStats,
    TyreStint,
)
from app.llm import Completion, JsonSchema, LLMInvalidResponseError, Message
from app.reports.facts import IncompleteRaceError, ReportFacts, build_facts
from app.reports.writer import (
    KEY_NUMBERS,
    MODEL_SECTIONS,
    ReportRejectedError,
    check_sections,
    invented_numbers,
    split_sections,
    write_report,
)

RACE = RaceDetail(
    id="2024-14",
    season=2024,
    round=14,
    event_name="Belgian Grand Prix",
    circuit_name="Spa-Francorchamps",
    event_date="2024-07-28",
    state="ingested",
    winner_name="Lewis Hamilton",
    has_report=False,
    total_laps=44,
    fastest_lap_time="1:44.701",
    fastest_lap_driver="Sergio Perez",
    safety_car_periods=0,
    winning_margin=None,
)


def row(
    position: int, name: str, code: str, grid: int, status: str = "Finished"
) -> ClassificationRow:
    return ClassificationRow(
        position=position,
        driver_name=name,
        driver_code=code,
        constructor_name="Team",
        grid_position=grid,
        points=25.0 if position == 1 else 0.0,
        status=status,
        best_lap_time="1:46.653",
        pit_stop_count=2,
        gap_to_leader=None,
    )


STATS = RaceStats(
    classification=[
        row(1, "Lewis Hamilton", "HAM", 3),
        row(2, "Max Verstappen", "VER", 11),
        row(3, "George Russell", "RUS", 6, status="Disqualified"),
    ],
    position_changes=[
        PositionChange(
            driver_name="Max Verstappen",
            driver_code="VER",
            grid_position=11,
            finish_position=2,
            positions_gained=9,
        ),
        PositionChange(
            driver_name="Lewis Hamilton",
            driver_code="HAM",
            grid_position=3,
            finish_position=1,
            positions_gained=2,
        ),
        PositionChange(
            driver_name="George Russell",
            driver_code="RUS",
            grid_position=6,
            finish_position=3,
            positions_gained=3,
        ),
    ],
    pace_traces=[],
    strategies=[
        DriverStrategy(
            driver_name="Lewis Hamilton",
            driver_code="HAM",
            stop_count=2,
            stints=[
                TyreStint(compound="MEDIUM", start_lap=1, end_lap=11),
                TyreStint(compound="HARD", start_lap=12, end_lap=26),
                TyreStint(compound="HARD", start_lap=27, end_lap=44),
            ],
        )
    ],
    pit_stops=[
        PitStopRow(
            driver_name="Daniel Ricciardo", driver_code="RIC", lap=21, duration_seconds=22.231
        ),
        PitStopRow(driver_name="Lewis Hamilton", driver_code="HAM", lap=11, duration_seconds=23.5),
    ],
    race_control=[
        RaceControlEventOut(lap=44, event_type="Flag", message="CHEQUERED FLAG", timestamp=None),
        RaceControlEventOut(
            lap=3,
            event_type="Other",
            message="5 SECOND TIME PENALTY FOR CAR 4 (NOR)",
            timestamp=None,
        ),
        RaceControlEventOut(
            lap=5, event_type="Flag", message="BLUE FLAG FOR CAR 2 (SAR)", timestamp=None
        ),
    ],
)
FACTS = ReportFacts(RACE, STATS)


def good_report(**overrides: str) -> str:
    bodies = {
        heading: f"{heading} of the Belgian Grand Prix, told from the facts only."
        for heading in MODEL_SECTIONS
    }
    bodies["Race Overview"] = (
        "Lewis Hamilton won over 44 laps; Sergio Perez set the fastest lap, 1:44.701."
    )
    bodies.update(overrides)
    return "\n\n".join(f"## {heading}\n{body}" for heading, body in bodies.items())


class TestFacts:
    def test_the_fact_sheet_states_what_the_page_shows(self) -> None:
        text = FACTS.text()

        assert "Winner: Lewis Hamilton." in text
        assert "Fastest lap: Sergio Perez, 1:44.701." in text
        assert "1. Lewis Hamilton, Team, grid 3, 25 pts, Finished, best 1:46.653, 2 stops" in text
        assert "Max Verstappen +9 (grid 11 to 2)" in text
        assert "RETIREMENTS: George Russell (Disqualified)" in text
        assert "Daniel Ricciardo 22.231 s on lap 21" in text

    def test_stop_counts_are_stated_next_to_the_stints(self) -> None:
        # Seen live: three stints were described as a "three-stop" race.
        assert "Lewis Hamilton (2 stops): MEDIUM 1-11, HARD 12-26, HARD 27-44" in FACTS.text()

    def test_only_notable_race_control_messages_are_kept(self) -> None:
        text = FACTS.text()

        assert "PENALTY FOR CAR 4" in text
        # "cheque-RED FLAG" once matched as a red flag.
        assert "CHEQUERED" not in text
        assert "BLUE FLAG" not in text

    def test_key_numbers_are_written_in_python(self) -> None:
        assert FACTS.key_numbers() == (
            "Laps: 44 · Winner: Lewis Hamilton · Fastest lap: 1:44.701 (Sergio Perez) · "
            "Safety car periods: 0 · Pit stops: 2 · Biggest gain: Max Verstappen (+9) · "
            "Classified finishers: 2 of 3"
        )

    @pytest.mark.parametrize(
        ("race", "stats", "reason"),
        [
            (None, STATS, "not stored"),
            (
                RACE,
                RaceStats(
                    classification=[],
                    position_changes=[],
                    pace_traces=[],
                    strategies=[],
                    pit_stops=[],
                    race_control=[],
                ),
                "no classification",
            ),
            (RACE.model_copy(update={"winner_name": None}), STATS, "no winner"),
        ],
    )
    def test_an_incomplete_race_is_refused_with_a_reason(
        self, race: RaceDetail | None, stats: RaceStats, reason: str
    ) -> None:
        with pytest.raises(IncompleteRaceError, match=reason):
            build_facts(race, stats)


class TestChecks:
    def test_a_good_report_passes_in_order(self) -> None:
        sections = check_sections(good_report(), FACTS.text())

        assert [s.heading for s in sections] == list(MODEL_SECTIONS)

    @pytest.mark.parametrize("number", ["1:43.999", "87", "12.5"])
    def test_a_number_not_in_the_facts_is_rejected(self, number: str) -> None:
        text = good_report(Strategy=f"Hamilton's stint was worth {number} over the field somehow.")

        with pytest.raises(ReportRejectedError, match=number):
            check_sections(text, FACTS.text())

    def test_small_counts_and_positions_need_no_source(self) -> None:
        assert invented_numbers("P3, two stops, 17 laps, 2024", "2024") == []

    def test_a_missing_or_thin_section_is_rejected(self) -> None:
        text = good_report(Takeaways="Short.")

        with pytest.raises(ReportRejectedError, match="Takeaways"):
            check_sections(text, FACTS.text())

    def test_a_repeated_heading_is_rejected(self) -> None:
        with pytest.raises(ReportRejectedError, match="twice"):
            split_sections("## Strategy\nOne.\n## Strategy\nTwo.")

    def test_headings_tolerate_markdown_variants(self) -> None:
        sections = split_sections("### **Race Overview**\nBody one.\n# Strategy\nBody two.")

        assert sections == {"Race Overview": "Body one.", "Strategy": "Body two."}


class ScriptedLLM:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.efforts: list[str | None] = []

    @property
    def model(self) -> str:
        return "scripted"

    async def complete(
        self,
        messages: list[Message],
        *,
        schema: JsonSchema | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        reasoning_effort: str | None = None,
    ) -> Completion:
        self.prompts.append(messages[-1].content)
        self.efforts.append(reasoning_effort)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply, model="scripted")


class TestWriting:
    async def test_key_numbers_go_in_before_the_takeaways(self) -> None:
        llm = ScriptedLLM(good_report())

        report = await write_report(llm, FACTS)

        headings = [s.heading for s in report.sections]
        assert headings[-2:] == [KEY_NUMBERS, "Takeaways"]
        assert report.sections[-2].body == FACTS.key_numbers()
        assert report.model == "scripted"
        assert "## Race Overview" in report.content()

    async def test_writing_asks_for_low_reasoning(self) -> None:
        # Default effort spent the whole budget thinking and wrote nothing.
        llm = ScriptedLLM(good_report())

        await write_report(llm, FACTS)

        assert llm.efforts == ["low"]

    async def test_an_invented_number_is_sent_back_once(self) -> None:
        bad = good_report(Strategy="The undercut was worth 3.456 seconds to Hamilton that day.")
        llm = ScriptedLLM(bad, good_report())

        await write_report(llm, FACTS)

        assert "these numbers are not in the facts: 3.456" in llm.prompts[1]

    async def test_two_failures_fail_rather_than_store_a_fabrication(self) -> None:
        bad = good_report(Strategy="The undercut was worth 3.456 seconds to Hamilton that day.")
        llm = ScriptedLLM(bad, bad)

        with pytest.raises(ReportRejectedError):
            await write_report(llm, FACTS)

    async def test_a_model_failure_is_not_swallowed(self) -> None:
        with pytest.raises(LLMInvalidResponseError):
            await write_report(ScriptedLLM(LLMInvalidResponseError("x")), FACTS)
