"""Race reports: read a stored one, or ask for one to be written.

Paths match `frontend/lib/api/reports.ts`. Generation returns a job id at
once; the page follows it through `GET /api/jobs/{id}` like an ingestion job.
Asking for a race that already has a report returns a job that is finished
before it is polled, so the page just reloads the report.

`POST .../report/generate` is one of the endpoints that spends real money
(tokens), so it refuses races that cannot have a report before any job
exists: unknown rounds and races that have not been run.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request

from app.api.routes.races import parse_race_id
from app.api.schemas.report import ReportJobAccepted, ReportOut
from app.db.models.enums import SessionType
from app.ingestion.schedule import session_has_started
from app.reports import store
from app.reports.jobs import ReportBusyError

router = APIRouter(prefix="/api", tags=["reports"])

RETRY_AFTER_SECONDS = 60


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


@router.get("/races/{race}/report", response_model=ReportOut)
async def race_report(race: str, request: Request) -> ReportOut:
    season, round_number = parse_race_id(race)
    async with request.app.state.database.connect(read_only=True) as connection:
        report = await store.report_for_race(connection, season, round_number)
    if report is None:
        raise HTTPException(404, detail="No report for this race yet")
    return ReportOut.from_stored(report)


@router.get("/reports/{report_id}", response_model=ReportOut)
async def report_by_id(report_id: str, request: Request) -> ReportOut:
    if not report_id.isdigit() or len(report_id) > 12:
        raise HTTPException(404, detail="Unknown report")
    async with request.app.state.database.connect(read_only=True) as connection:
        report = await store.report_by_id(connection, int(report_id))
    if report is None:
        raise HTTPException(404, detail="Unknown report")
    return ReportOut.from_stored(report)


@router.post("/races/{race}/report/generate", response_model=ReportJobAccepted, status_code=202)
async def generate_report(race: str, request: Request) -> ReportJobAccepted:
    reports = request.app.state.reports
    if reports is None:
        raise HTTPException(
            503,
            detail="Report writing is not configured on this server.",
            headers={"Retry-After": "3600"},
        )
    season, round_number = parse_race_id(race)
    schedule = await request.app.state.schedules.get(season)
    event = next((e for e in schedule if e.round_number == round_number), None)
    if schedule and event is None:
        raise HTTPException(404, detail="Unknown race")
    if event is not None and not session_has_started(event.event_date, SessionType.RACE, _today()):
        raise HTTPException(409, detail="This race has not been run yet.")

    try:
        job_id = await reports.submit(season, round_number)
    except ReportBusyError as error:
        raise HTTPException(
            503,
            detail="Other reports are being written. Try again in a minute.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        ) from error
    return ReportJobAccepted(job_id=job_id)
