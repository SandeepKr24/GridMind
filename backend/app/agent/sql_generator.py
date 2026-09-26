"""Ask the model for one read-only query that answers the question.

The model gets the six tables a session question can need, described by hand
rather than dumped from the metadata: every column note below is something a
plausible query got wrong without it (safety-car laps counted as race pace,
pit-lane time read as stationary time, a string "1" compared to an integer).
Sessions, drivers and teams arrive as ids from `session_context.py`, so the
query never joins through the calendar to find them.

It returns JSON: the query, or a reason the stored data cannot answer. Asking
for a reason instead of forcing SQL is how "why did Ferrari struggle?" gets
an honest "the data shows X, not why" rather than an invented query.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.agent.session_context import SessionContext
from app.llm import JsonSchema, LLMInvalidResponseError, LLMProvider, Message

#: Room for reasoning before the JSON; a query is rarely more than 150 tokens.
MAX_TOKENS = 2048
#: Every query is capped; the executor enforces it again regardless.
ROW_LIMIT = 50


class QueryType(StrEnum):
    """What kind of question it was. Echoed to the frontend as `query_type`."""

    RESULT = "result"
    COMPARISON = "comparison"
    PACE = "pace"
    QUALIFYING = "qualifying"
    TYRES = "tyres"
    PIT_STOPS = "pit_stops"
    RACE_CONTROL = "race_control"
    OTHER = "other"


SCHEMA_TEXT = """\
PostgreSQL tables. All times are integer milliseconds.
session_results(session_id, driver_id, constructor_id, position [null = not classified],
  grid_position [0 = pit lane start], points, status ['Finished','Lapped','Retired',
  'Disqualified', ...], total_laps, fastest_lap [boolean], fastest_lap_time_ms [only
  on the session's fastest-lap holder; anyone's best lap is MIN(laps.lap_time_ms)],
  q1_time_ms, q2_time_ms, q3_time_ms [qualifying sessions only])
laps(session_id, driver_id, lap_number, lap_time_ms [null for in-laps, out-laps and
  deleted laps], sector_1_ms, sector_2_ms, sector_3_ms, speed_trap_kph, position,
  compound ['SOFT','MEDIUM','HARD','INTERMEDIATE','WET', or null], tyre_life [laps on
  that set], is_personal_best, track_status [text of status codes seen during the lap:
  '1' green, '2' yellow, '4' safety car, '5' red flag, '6' VSC, '7' VSC ending.
  Exactly '1' means a clean green-flag lap])
pit_stops(session_id, driver_id, stop_number, lap_number [the in-lap], duration_ms
  [time through the pit lane, entry to exit; not the stationary time])
race_control_events(session_id, driver_id [null when session-wide], lap_number,
  category ['Flag','SafetyCar','Drs','Other'], flag ['YELLOW','DOUBLE YELLOW','RED',
  'BLUE','GREEN','CLEAR','CHEQUERED','BLACK AND WHITE', or null], scope ['Track',
  'Sector','Driver'], message [upper case FIA wording. One safety car or VSC logs
  several messages; count deployments with message LIKE '%DEPLOYED%'. Other
  messages have category 'Other' and driver_id set when they name a single car:
  deleted time 'CAR 4 (NOR) TIME 1:50.504 DELETED - TRACK LIMITS AT TURN 6',
  penalty 'FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) - ...',
  investigation '... INCIDENT INVOLVING CAR 23 (ALB) NOTED/UNDER INVESTIGATION'.
  Match on single words: LIKE '%DELETED%', '%PENALTY%', '%INVESTIGATION%'])
drivers(id, driver_code, first_name, last_name, full_name)
constructors(id, name)"""

SYSTEM_PROMPT = f"""\
You write one PostgreSQL SELECT query that answers a Formula 1 question from the
tables below, and return it as JSON.

{SCHEMA_TEXT}

Rules:
- One SELECT (WITH is allowed). Never write, create, alter or grant anything.
- Filter every timing table by the session ids given. Never look sessions up by name.
- Use the driver and constructor ids given for anyone the question names.
- Return readable columns (drivers.full_name, constructors.name), not bare ids, and
  alias them for display: driver, team, position, points, lap_time_ms, and so on.
- Keep times in milliseconds; do not format them. Name such columns *_ms.
- For race pace, use laps with lap_time_ms not null and track_status = '1'. Only
  for pace: counting laps (e.g. laps led, position = 1) uses every lap.
- For tyre strategy, read stints from laps: consecutive laps on one compound. The
  compound on a pit stop's lap is the set coming off.
- Compute counts, averages and differences in SQL. Add LIMIT {ROW_LIMIT} at most.
- Aggregate each of laps, pit_stops and race_control_events in its own CTE before
  joining them. Joining two of them directly multiplies rows and corrupts COUNT/SUM.
- One row per item. Do not pack results into arrays or JSON.
- Keep the query short and simple: the smallest query that answers the question.
- For "why" or open-ended questions, do not try to explain in SQL. Return the
  main evidence (e.g. finishing positions and points, or average green-flag lap
  time per driver) and let the answer interpret it.
- If these tables cannot answer the question, set sql to null and say why in
  cannot_answer. Never guess."""

SCHEMA = JsonSchema(
    name="sql_query",
    schema={
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "enum": [q.value for q in QueryType]},
            "sql": {"type": ["string", "null"]},
            "cannot_answer": {"type": ["string", "null"]},
        },
        "required": ["query_type", "sql", "cannot_answer"],
        "additionalProperties": False,
    },
)


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query_type: QueryType = QueryType.OTHER
    sql: str | None = None
    cannot_answer: str | None = None

    @field_validator("sql", "cannot_answer")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


@dataclass(frozen=True, slots=True)
class GeneratedQuery:
    query_type: QueryType
    sql: str | None
    #: Set when sql is None: the model's reason the data cannot answer.
    cannot_answer: str | None


def describe_context(context: SessionContext) -> str:
    lines = ["Sessions:"]
    lines += [f"- session_id {s.session_id}: {s.session.describe()}" for s in context.sessions]
    if context.drivers:
        lines.append(
            "Drivers named: " + "; ".join(f"{d.label} = driver_id {d.id}" for d in context.drivers)
        )
    if context.constructors:
        lines.append(
            "Teams named: "
            + "; ".join(f"{c.label} = constructor_id {c.id}" for c in context.constructors)
        )
    return "\n".join(lines)


def build_messages(
    question: str, context: SessionContext, previous_error: str | None = None
) -> list[Message]:
    user = f"{describe_context(context)}\nQuestion: {question.strip()}"
    if previous_error is not None:
        user += f"\nYour previous query failed: {previous_error}\nWrite a corrected query."
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


def parse_output(payload: dict[str, object]) -> GeneratedQuery:
    try:
        output = _Output.model_validate(payload)
    except ValidationError as error:
        raise LLMInvalidResponseError(f"SQL generation did not fit the schema: {error}") from error
    if output.sql is None and output.cannot_answer is None:
        raise LLMInvalidResponseError("SQL generation returned neither a query nor a reason")
    return GeneratedQuery(
        query_type=output.query_type,
        sql=output.sql.rstrip(";").strip() if output.sql else None,
        cannot_answer=None if output.sql else output.cannot_answer,
    )


async def generate_sql(
    llm: LLMProvider,
    question: str,
    context: SessionContext,
    *,
    previous_error: str | None = None,
) -> GeneratedQuery:
    completion = await llm.complete(
        build_messages(question, context, previous_error), schema=SCHEMA, max_tokens=MAX_TOKENS
    )
    return parse_output(completion.json())
