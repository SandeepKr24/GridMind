"""Generated race reports.

Reports are expensive to produce — several LLM calls over stored data — so they
are written once and served from here afterwards. `content` holds the rendered
report; `sections` holds the structured form the frontend renders.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, pg_enum, pk, utc_now
from app.db.models.enums import ReportTrigger, ReportType


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        # One report of each type per weekend. Regenerating replaces it rather
        # than accumulating near-identical copies.
        UniqueConstraint("meeting_id", "report_type"),
    )

    id: Mapped[int] = pk()
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[ReportType] = mapped_column(
        pg_enum(ReportType, "report_type"), nullable=False
    )
    trigger: Mapped[ReportTrigger] = mapped_column(
        pg_enum(ReportTrigger, "report_trigger"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSONB rather than JSON: it is queried, and JSONB can be indexed.
    sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Which model wrote it, so a report can be traced when the catalogue moves.
    model: Mapped[str | None] = mapped_column(String(128))
    generated_at: Mapped[dt.datetime] = utc_now()
