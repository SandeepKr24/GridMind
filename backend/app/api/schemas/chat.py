"""Wire models for chat.

Mirrors `ChatResponse`, `ChatTable` and `ResolvedEntities` in
`frontend/lib/api/types.ts`. Field names are the contract;
`tests/test_chat_route.py` pins them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.agent.entities import ResolvedEntities
from app.agent.orchestrator import ChatReply
from app.db.models.enums import SessionType

#: Matches MAX_QUESTION_LENGTH in frontend/lib/hooks/useUrlParam.ts.
MAX_QUESTION_LENGTH = 500


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class ChatTableOut(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class ResolvedEntitiesOut(BaseModel):
    year: int | None
    round: int | None
    grand_prix: str | None
    session_type: SessionType | None
    drivers: list[str]

    @classmethod
    def from_entities(cls, entities: ResolvedEntities) -> ResolvedEntitiesOut:
        # The frontend shows one race; the first session is the one asked about.
        first = entities.sessions[0] if entities.sessions else None
        return cls(
            year=first.year if first else entities.year,
            round=first.round_number if first else None,
            grand_prix=first.grand_prix if first else None,
            session_type=first.session_type if first else None,
            drivers=list(entities.drivers),
        )


class IngestionOut(BaseModel):
    required: bool
    job_id: str | None


class ChatResponse(BaseModel):
    answer: str
    data: list[dict[str, str | int | float | None]]
    table: ChatTableOut | None
    sources: list[str]
    query_type: str | None
    resolved_entities: ResolvedEntitiesOut | None
    ingestion: IngestionOut | None
    needs_clarification: bool
    clarifying_question: str | None
    conversation_id: str

    @classmethod
    def from_reply(cls, reply: ChatReply, conversation_id: str) -> ChatResponse:
        table = reply.table
        return cls(
            answer=reply.answer,
            data=table.records() if table else [],  # type: ignore[arg-type]
            table=ChatTableOut(columns=list(table.columns), rows=[list(r) for r in table.rows])
            if table
            else None,
            sources=list(reply.sources),
            query_type=reply.query_type,
            resolved_entities=ResolvedEntitiesOut.from_entities(reply.entities)
            if reply.entities
            else None,
            ingestion=IngestionOut(required=True, job_id=reply.job_id) if reply.job_id else None,
            needs_clarification=reply.clarifying_question is not None,
            clarifying_question=reply.clarifying_question,
            conversation_id=conversation_id,
        )
