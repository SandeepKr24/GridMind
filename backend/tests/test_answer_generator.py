"""Answer writing: the deterministic table, and what the model is told."""

from __future__ import annotations

import pytest

from app.agent.answer_generator import (
    EMPTY_CELL,
    SYSTEM_PROMPT,
    build_messages,
    build_table,
    column_label,
    format_cell,
    generate_answer,
)
from tests.test_sql_generator import FakeLLM


class TestTable:
    @pytest.mark.parametrize(
        ("column", "label"),
        [
            ("avg_lap_time_ms", "avg lap time"),
            ("q3_time_ms", "q3 time"),
            ("driver", "driver"),
            ("positions_gained", "positions gained"),
            ("_ms", "_ms"),
        ],
    )
    def test_labels_drop_the_unit_and_underscores(self, column: str, label: str) -> None:
        assert column_label(column) == label

    @pytest.mark.parametrize(
        ("column", "value", "cell"),
        [
            ("lap_time_ms", 109245, "1:49.245"),
            ("avg_lap_time_ms", 109245.6511, "1:49.246"),
            ("duration_ms", 22231, "22.231"),
            ("points", 25, "25"),
            ("points", 12.5, "12.5"),
            ("gap", 0.1234567, "0.123"),
            ("fastest_lap", True, "yes"),
            ("driver", "Lando Norris", "Lando Norris"),
            ("lap_time_ms", None, EMPTY_CELL),
        ],
    )
    def test_cells_are_formatted_for_reading(self, column: str, value: object, cell: str) -> None:
        assert format_cell(column, value) == cell

    def test_a_table_and_its_records(self) -> None:
        table = build_table(("driver", "lap_time_ms"), [("Lando Norris", 113981)])

        assert table.columns == ("driver", "lap time")
        assert table.rows == (("Lando Norris", "1:53.981"),)
        assert table.records() == [{"driver": "Lando Norris", "lap time": "1:53.981"}]
        assert table.as_text() == "driver | lap time\nLando Norris | 1:53.981"


class TestPrompt:
    @pytest.mark.parametrize(
        "rule",
        [
            "Never invent",
            "nothing matching",
            "Quote them as given",
            "cannot establish the cause",
            "was assumed, mention it",
            "do not claim the list is complete",
        ],
    )
    def test_the_rules_that_keep_answers_honest_are_present(self, rule: str) -> None:
        assert rule in SYSTEM_PROMPT

    def test_the_model_sees_the_source_question_and_rows(self) -> None:
        table = build_table(("driver",), [("Lewis Hamilton",)])

        _, user = build_messages(
            "Who won?", "the 2024 Belgian Grand Prix race", table, truncated=False
        )

        assert user.content == (
            "Data: the 2024 Belgian Grand Prix race\n"
            "Question: Who won?\n"
            "Result (1 rows):\n"
            "driver\n"
            "Lewis Hamilton"
        )

    def test_an_empty_or_cut_result_is_said_so(self) -> None:
        empty = build_table(("driver",), [])

        _, user = build_messages("Penalties?", "note", empty, truncated=True)

        assert "(0 rows, only the first rows are shown)" in user.content
        assert user.content.endswith("(no rows)")

    async def test_the_answer_is_the_models_text_trimmed(self) -> None:
        llm = FakeLLM("  Hamilton won.  \n")

        answer = await generate_answer(llm, "Who won?", "note", build_table(("d",), [("x",)]))

        assert answer == "Hamilton won."
        _, schema, _ = llm.calls[0]
        assert schema is None  # prose, not JSON
