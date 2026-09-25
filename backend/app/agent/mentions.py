"""The model's half of entity resolution: what does the question mention?

The model only transcribes. It reports the race as the user wrote it, a year
if one was stated, and "latest"/"previous" markers for relative phrases. Date
arithmetic, calendar lookup and every judgement about ambiguity happen in
Python (`entity_resolver.py`), because the model's sense of "last year" or of
which round Monza is can be wrong, and those errors would be silent.

The prompt is short on purpose: the free tier allows 8K tokens a minute, and
this call runs on every chat message.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.agent.entities import Intent, ResolvedEntities
from app.db.models.enums import SessionType
from app.llm import JsonSchema, LLMInvalidResponseError, LLMProvider, Message

#: The ingestion gate allows at most a couple of sessions; anything past this
#: is a season-wide question in disguise and gets refused there.
MAX_TARGETS = 4
MAX_NAMES = 6
#: Reasoning models spend completion tokens thinking before the JSON starts.
MAX_TOKENS = 1024

Reference = Literal["first", "latest", "next"]
RelativeYear = Literal["current", "previous"]


class TargetMention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    race: str | None = None
    reference: Reference | None = None
    year: int | None = None
    relative_year: RelativeYear | None = None
    session: SessionType | None = None

    @field_validator("race")
    @classmethod
    def _blank_race_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def _a_named_race_beats_a_reference(self) -> TargetMention:
        # Seen live: a follow-up came back as race "Hungarian Grand Prix" plus
        # reference "latest", which would silently pick a different round.
        if self.race is not None and self.reference is not None:
            return self.model_copy(update={"reference": None})
        return self


class Mentions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    intent: Intent
    year: int | None = None
    relative_year: RelativeYear | None = None
    targets: tuple[TargetMention, ...] = Field(default=())
    drivers: tuple[str, ...] = Field(default=())
    constructors: tuple[str, ...] = Field(default=())
    follow_up: bool = False

    @field_validator("targets")
    @classmethod
    def _cap_targets(cls, value: tuple[TargetMention, ...]) -> tuple[TargetMention, ...]:
        return value[:MAX_TARGETS]

    @model_validator(mode="after")
    def _named_race_means_a_session_question(self) -> Mentions:
        # Seen live on low reasoning effort: "how did the first race of 2024
        # go?" labelled season-wide. A question that points at a race is not.
        names_a_race = any(t.race or t.reference for t in self.targets)
        if self.intent is Intent.SEASON and names_a_race:
            return self.model_copy(update={"intent": Intent.SESSION})
        return self

    @field_validator("drivers", "constructors")
    @classmethod
    def _clean_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = [name.strip() for name in value if name.strip()]
        return tuple(dict.fromkeys(cleaned))[:MAX_NAMES]


def _nullable(json_type: str, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": [json_type, "null"]}
    if enum is not None:
        schema["enum"] = [*enum, None]
    return schema


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    # Strict mode: every property required, nothing extra.
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TARGET = _object(
    {
        "race": _nullable("string"),
        "reference": _nullable("string", ["first", "latest", "next"]),
        "year": _nullable("integer"),
        "relative_year": _nullable("string", ["current", "previous"]),
        "session": _nullable("string", [s.value for s in SessionType]),
    }
)

SCHEMA = JsonSchema(
    name="question_entities",
    schema=_object(
        {
            "intent": {"type": "string", "enum": [i.value for i in Intent]},
            "year": _nullable("integer"),
            "relative_year": _nullable("string", ["current", "previous"]),
            "targets": {"type": "array", "items": _TARGET},
            "drivers": {"type": "array", "items": {"type": "string"}},
            "constructors": {"type": "array", "items": {"type": "string"}},
            "follow_up": {"type": "boolean"},
        }
    ),
)

SYSTEM_PROMPT = """\
You read questions about Formula 1 and report what they mention, as JSON.
Transcribe only what the question says. Never guess or fill in a missing value.

intent:
- session: about specific sessions (a race, qualifying, practice, sprint).
- season: needs many races of one season, e.g. "who had the most DNFs in 2024".
  Never season when the question names one race.
- standings: championship points or positions.
- unsupported: not about Formula 1 results or data.

targets: one entry per specific race weekend the question names. Empty if none.
- race: the race or circuit as written ("Monza", "British GP"), else null.
- reference: "latest" for the last or most recent race, "next" for the next race,
  "first" for the season opener. null when race is set.
- year: a year stated for this race, else null.
- relative_year: "current" for this year or this season, "previous" for last year, else null.
- session: practice_1, practice_2, practice_3, qualifying (also Q1, Q2, Q3, pole),
  sprint_qualifying (also SQ1-SQ3, sprint shootout), sprint, race. null if not stated.

year, relative_year (top level): a year stated for the whole question.
drivers: drivers named, as surnames. Turn nicknames and codes into surnames
("Checo" -> "Perez", "VER" -> "Verstappen").
constructors: teams named.
follow_up: true only if the question cannot be understood without the previous
question, e.g. "and Leclerc?" or "what about qualifying?"."""


def _context_line(previous: ResolvedEntities) -> str:
    parts = [s.describe() for s in previous.sessions]
    if not parts and previous.year is not None:
        parts.append(f"the {previous.year} season")
    if previous.drivers:
        parts.append("drivers " + ", ".join(previous.drivers))
    return "Previous question was about: " + ("; ".join(parts) or previous.intent.value)


def build_messages(question: str, previous: ResolvedEntities | None) -> list[Message]:
    user = f"Question: {question.strip()}"
    if previous is not None:
        user = f"{_context_line(previous)}\n{user}"
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


def parse_mentions(payload: dict[str, Any]) -> Mentions:
    try:
        return Mentions.model_validate(payload)
    except ValidationError as error:
        raise LLMInvalidResponseError(
            f"entity extraction did not fit the schema: {error}"
        ) from error


async def extract_mentions(
    llm: LLMProvider, question: str, previous: ResolvedEntities | None = None
) -> Mentions:
    completion = await llm.complete(
        build_messages(question, previous), schema=SCHEMA, max_tokens=MAX_TOKENS
    )
    return parse_mentions(completion.json())
