import { request } from "./client";
import type { IngestionJob, SessionType } from "./types";

/** Job polls get a long timeout: the backend may be mid-fetch and slow to answer. */
const JOB_TIMEOUT_MS = 30_000;

export function getJob(jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/jobs/${encodeURIComponent(jobId)}`, {
    timeoutMs: JOB_TIMEOUT_MS,
  });
}

export function triggerIngest(params: {
  year: number;
  round: number;
  session: SessionType;
}): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/api/ingest`, {
    method: "POST",
    body: {
      season_year: params.year,
      round_number: params.round,
      session_type: params.session,
    },
  });
}

export function isJobFinished(job: IngestionJob): boolean {
  return (
    job.status === "succeeded" ||
    job.status === "failed" ||
    job.status === "skipped_cached"
  );
}

export function didJobSucceed(job: IngestionJob): boolean {
  return job.status === "succeeded" || job.status === "skipped_cached";
}
