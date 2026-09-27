"""Ingestion endpoints: start a session fetch, and poll it.

Paths match `frontend/lib/api/jobs.ts`. `POST /api/ingest` is one of the
endpoints that costs real resources, so it refuses anything that cannot
produce data before a job is ever created: seasons out of range, rounds not on
the calendar, and races that have not run.

`force: true` re-ingests a stored session. It shares the ingest rate limit,
so it cannot be used to keep the provider busy.
"""

from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limit import rate_limit
from app.api.schemas.job import IngestAccepted, IngestRequest, JobOut
from app.ingestion.jobs import JobKey
from app.ingestion.runner import IngestBusyError
from app.ingestion.schedule import FIRST_SEASON, session_has_started
from app.reports.jobs import JOB_PREFIX as REPORT_JOB_PREFIX

router = APIRouter(prefix="/api", tags=["jobs"])

#: What the frontend accepts in `?job=`; anything else is not one of ours.
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

RETRY_AFTER_SECONDS = 60


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


async def _check_can_have_data(request: Request, body: IngestRequest) -> None:
    today = _today()
    if not FIRST_SEASON <= body.season_year <= today.year:
        raise HTTPException(status_code=404, detail="Unknown race")

    schedule = await request.app.state.schedules.get(body.season_year)
    if not schedule:
        # Calendar unavailable: let the job try, and fail honestly if it must.
        return
    event = next((e for e in schedule if e.round_number == body.round_number), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Unknown race")
    if not session_has_started(event.event_date, body.session_type, today):
        raise HTTPException(status_code=409, detail="This session has not run yet.")


@router.post(
    "/ingest",
    response_model=IngestAccepted,
    status_code=202,
    dependencies=[Depends(rate_limit("ingest"))],
)
async def ingest(body: IngestRequest, request: Request) -> IngestAccepted:
    await _check_can_have_data(request, body)
    key = JobKey(body.season_year, body.round_number, body.session_type)
    try:
        submission = await request.app.state.runner.submit(key, force=body.force)
    except IngestBusyError as error:
        raise HTTPException(
            status_code=503,
            detail="The server is busy fetching other sessions. Try again in a minute.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        ) from error
    return IngestAccepted(job_id=submission.job_id)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job_status(job_id: str, request: Request) -> JobOut:
    if not JOB_ID.match(job_id):
        raise HTTPException(status_code=404, detail="Unknown job")
    if job_id.startswith(REPORT_JOB_PREFIX):
        reports = request.app.state.reports
        record = reports.get(job_id) if reports is not None else None
    else:
        record = await request.app.state.runner.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return JobOut.from_record(record)
