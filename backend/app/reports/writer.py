"""The model writes the report's prose; this module decides whether to keep it.

The model gets the fact sheet from `facts.py` and writes six sections, each
opened by a `## Heading` line. Plain text, not JSON: asked for strict JSON,
gpt-oss spent its whole token budget reasoning and produced nothing, and a
report is prose anyway. Reasoning is set to "low" for the same reason. The
facts are already worked out, so there is little left to reason about.

Before anything is stored, the output is checked:

- every required heading is present, once, with a real body;
- every number in the prose appears in the fact sheet. Small integers are
  exempt, because positions, stop counts and "two-stop" are everywhere and
  are also in the facts. A lap time, points total or percentage that is not
  in the facts is an invented statistic, which the plan forbids.

A failed check is sent back once with the problem named. A second failure
fails the job: an honest error is better than a stored fabrication, and the
report would be served forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.llm import LLMProvider, Message
from app.reports.facts import ReportFacts

#: Written by the model, in this order.
MODEL_SECTIONS = (
    "Race Overview",
    "Qualifying vs Race",
    "Driver Performance",
    "Strategy",
    "Race Story",
    "Takeaways",
)
#: Written in Python and inserted before the takeaways.
KEY_NUMBERS = "Key Numbers"
#: Groq reserves this against the per-minute token budget when the request is
#: made, so it is sized to the job: low-effort reports used about 700 tokens.
MAX_TOKENS = 2500
#: Whole numbers this small need no source: positions, counts, "two-stop".
FREE_NUMBER_LIMIT = 30
MIN_BODY_LENGTH = 40

_NUMBER = re.compile(r"\d+(?:[.:]\d+)*")
_HEADING = re.compile(r"^\s*#{1,3}\s*(.+?)\s*$", re.MULTILINE)

SYSTEM_PROMPT = f"""\
You are GridMind, a Formula 1 race analyst writing a post-race report. Use only
the facts given. Write one section per heading, each starting with a line
"## <heading>", in this order: {", ".join(MODEL_SECTIONS)}.

- Never invent a fact, number, quote or reason. Every number you write must
  appear in the facts exactly as given (times such as 1:44.701 included).
- Do not calculate new numbers: no averages, gaps, percentages or totals that
  the facts do not already state.
- Stop counts are given per driver. A driver with three stints made two stops.
- The facts give where each driver started and finished, not the order during
  the race. Do not say who led, battled, overtook or held position on track.
- Pole means grid 1 and the front row means grids 1 and 2; say neither
  otherwise.
- Never explain why a result happened ("thanks to", "shows the effectiveness
  of", "the advantage of"). Report what happened; the facts hold no causes.
- Race Story tells the race from the facts: the start-to-finish movements, the
  strategies, retirements and race control events.
- Driver Performance picks out the notable drives; do not list every driver.
- Takeaways: two or three short observations, each a fact, not a judgement.
- Each section is one or two paragraphs of plain text. No lists, no bold."""


class ReportRejectedError(ValueError):
    """The model's report failed the checks. The message says why."""


@dataclass(frozen=True, slots=True)
class Section:
    heading: str
    body: str


@dataclass(frozen=True, slots=True)
class WrittenReport:
    sections: tuple[Section, ...]
    model: str

    def content(self) -> str:
        return "\n\n".join(f"## {s.heading}\n\n{s.body}" for s in self.sections)


def split_sections(text: str) -> dict[str, str]:
    """`## Heading` blocks as heading -> body. Repeated headings are an error."""
    matches = list(_HEADING.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip().strip("*").strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if heading in sections:
            raise ReportRejectedError(f'the section "{heading}" appears twice')
        sections[heading] = text[match.end() : end].strip()
    return sections


def invented_numbers(text: str, facts_text: str) -> list[str]:
    """Numbers in `text` that the facts do not contain, in order of appearance."""
    known = set(_NUMBER.findall(facts_text))
    found: list[str] = []
    for number in _NUMBER.findall(text):
        if number in known or number in found:
            continue
        if number.isdigit() and int(number) <= FREE_NUMBER_LIMIT:
            continue
        found.append(number)
    return found


def check_sections(text: str, facts_text: str) -> tuple[Section, ...]:
    """The sections in order, or ReportRejectedError naming what is wrong."""
    by_heading = split_sections(text)
    missing = [h for h in MODEL_SECTIONS if len(by_heading.get(h, "")) < MIN_BODY_LENGTH]
    if missing:
        raise ReportRejectedError("these sections are missing or empty: " + ", ".join(missing))

    bodies = [by_heading[h] for h in MODEL_SECTIONS]
    invented = invented_numbers(" ".join(bodies), facts_text)
    if invented:
        raise ReportRejectedError(
            "these numbers are not in the facts: "
            + ", ".join(invented[:10])
            + ". Use only numbers the facts state, or leave them out"
        )
    return tuple(Section(h, by_heading[h]) for h in MODEL_SECTIONS)


def _with_key_numbers(sections: tuple[Section, ...], facts: ReportFacts) -> tuple[Section, ...]:
    return (*sections[:-1], Section(KEY_NUMBERS, facts.key_numbers()), sections[-1])


def build_messages(facts_text: str, feedback: str | None) -> list[Message]:
    user = f"FACTS\n{facts_text}"
    if feedback is not None:
        user += f"\n\nYour previous report was rejected: {feedback}. Write it again."
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


async def write_report(llm: LLMProvider, facts: ReportFacts, *, attempts: int = 2) -> WrittenReport:
    """Sections checked against the facts, with Key Numbers added in Python.

    Rate limits and outages propagate: the job decides whether to wait.
    """
    facts_text = facts.text()
    feedback: str | None = None
    for _ in range(attempts):
        completion = await llm.complete(
            build_messages(facts_text, feedback),
            max_tokens=MAX_TOKENS,
            temperature=0.3,
            reasoning_effort="low",
        )
        try:
            sections = check_sections(completion.text, facts_text)
        except ReportRejectedError as error:
            feedback = str(error)
            continue
        return WrittenReport(_with_key_numbers(sections, facts), completion.model)
    raise ReportRejectedError(f"the report did not pass its checks: {feedback}")
