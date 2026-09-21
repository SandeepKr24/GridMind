import { request } from "./client";
import type { Report } from "./types";

export function getRaceReport(raceId: string): Promise<Report> {
  return request<Report>(`/api/races/${encodeURIComponent(raceId)}/report`);
}

export function getReport(reportId: string): Promise<Report> {
  return request<Report>(`/api/reports/${encodeURIComponent(reportId)}`);
}

/**
 * Historic races have no report until someone asks. Generation is expensive and
 * returns a job id, so the caller drives the Loading Pit from it.
 */
export function generateReport(raceId: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(
    `/api/races/${encodeURIComponent(raceId)}/report/generate`,
    { method: "POST" }
  );
}
