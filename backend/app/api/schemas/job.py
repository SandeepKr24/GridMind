"""Wire models for ingestion jobs.

Mirrors `IngestionJob` and `triggerIngest` in `frontend/lib/api/`. Field names
are the contract; `tests/test_jobs_route.py` pins them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.schemas.race import iso
from app.db.models.enums import JobStage, JobStatus, SessionType
from app.ingestion.jobs import JobRecord


class IngestRequest(BaseModel):
    season_year: int
    # The longest season so far has 24 rounds; 30 leaves room without letting
    # arbitrary numbers through.
    round_number: int = Field(ge=1, le=30)
    session_type: SessionType


class IngestAccepted(BaseModel):
    job_id: str


class JobOut(BaseModel):
    id: str
    status: JobStatus
    stage: JobStage
    progress_percent: int | None
    season_year: int
    round_number: int
    session_type: SessionType
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    rows_written: int | None

    @classmethod
    def from_record(cls, record: JobRecord) -> JobOut:
        return cls(
            id=record.id,
            status=record.status,
            stage=record.stage,
            progress_percent=record.progress_percent,
            season_year=record.season_year,
            round_number=record.round_number,
            session_type=record.session_type,
            started_at=iso(record.started_at),
            finished_at=iso(record.finished_at),
            error_message=record.error_message,
            rows_written=record.rows_written,
        )
