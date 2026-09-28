"""Turn query rows into the reply: a table built in Python, prose by the model.

The table is deterministic. Millisecond columns become lap times here, with
the same formatter as the race pages, so the model quotes "1:49.245" instead
of doing arithmetic on 109245. The model only writes a few sentences over the
table, and is told the data's source and anything the resolver assumed, so
it can say "assuming the 2026 season" rather than hide it.

Replies that need no prose (clarifications, refusals, "the data can't answer
this") never reach this module and cost no tokens.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.api.schemas.race import format_lap_time
from app.llm import LLMProvider, Message

MAX_TOKENS = 1024
EMPTY_CELL = "-"

SYSTEM_PROMPT = """\
You are GridMind, a Formula 1 race analyst. Answer the question using only the
query result you are given.
- Never invent a statistic, name or value that is not in the result.
- If the result is empty, say the data shows nothing matching. Do not guess why.
- Times are already formatted as m:ss.sss or ss.sss. Quote them as given; do not
  recalculate or convert them.
- For a "why" question, describe what the data shows and say plainly that it
  cannot establish the cause.
- Name the race or championship the data is from, as the data note gives it.
- If the data note says a season or session was assumed, mention it.
- If only the first rows are shown, do not claim the list is complete.
- Answer in one to four sentences of plain text. No markdown and no tables; the
  table is shown to the user separately."""


@dataclass(frozen=True, slots=True)
class AnswerTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def records(self) -> list[dict[str, str]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def as_text(self) -> str:
        lines = [" | ".join(self.columns)]
        lines += [" | ".join(row) for row in self.rows]
        return "\n".join(lines)


def column_label(column: str) -> str:
    """`avg_lap_time_ms` -> `avg lap time`: the unit is gone once formatted."""
    name = column[: -len("_ms")] if column.lower().endswith("_ms") else column
    return name.replace("_", " ").strip() or column


def format_cell(column: str, value: object) -> str:
    if value is None:
        return EMPTY_CELL
    if column.lower().endswith("_ms") and isinstance(value, int | float):
        return format_lap_time(round(value)) or EMPTY_CELL
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def build_table(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> AnswerTable:
    return AnswerTable(
        columns=tuple(column_label(c) for c in columns),
        rows=tuple(
            tuple(format_cell(c, v) for c, v in zip(columns, row, strict=True)) for row in rows
        ),
    )


def build_messages(
    question: str, data_note: str, table: AnswerTable, *, truncated: bool
) -> list[Message]:
    shown = f"{len(table.rows)} rows" + (", only the first rows are shown" if truncated else "")
    body = table.as_text() if table.rows else "(no rows)"
    user = f"Data: {data_note}\nQuestion: {question.strip()}\nResult ({shown}):\n{body}"
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


async def generate_answer(
    llm: LLMProvider,
    question: str,
    data_note: str,
    table: AnswerTable,
    *,
    truncated: bool = False,
) -> str:
    completion = await llm.complete(
        build_messages(question, data_note, table, truncated=truncated),
        max_tokens=MAX_TOKENS,
        temperature=0.2,
    )
    return completion.text.strip()
