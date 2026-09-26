"""Wire models for race reports.

Mirrors `Report` and `ReportSection` in `frontend/lib/api/types.ts`.
`tests/test_reports_route.py` pins the field names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.api.schemas.common import iso, race_id
from app.llm.text import plain_text

if TYPE_CHECKING:
    # Only for the annotation: importing the store at runtime would loop back
    # through the analytics into the race schema.
    from app.reports.store import StoredReport


class ReportSectionOut(BaseModel):
    heading: str
    body: str


class ReportOut(BaseModel):
    id: str
    race_id: str
    event_name: str
    season: int
    report_type: str
    generated_at: str
    model: str
    trigger: str
    sections: list[ReportSectionOut]

    @classmethod
    def from_stored(cls, report: StoredReport) -> ReportOut:
        return cls(
            id=str(report.id),
            race_id=race_id(report.season, report.round_number),
            event_name=report.event_name,
            season=report.season,
            report_type=report.report_type.value,
            generated_at=iso(report.generated_at) or "",
            model=report.model or "unknown",
            trigger=report.trigger.value,
            sections=[
                # Reports written before completions were cleaned still hold
                # the model's narrow spaces; clean them on the way out.
                ReportSectionOut(
                    heading=plain_text(str(s.get("heading", ""))),
                    body=plain_text(str(s.get("body", ""))),
                )
                for s in report.sections
            ],
        )


class ReportJobAccepted(BaseModel):
    job_id: str
