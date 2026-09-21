import { request } from "./client";
import type {
  CalendarRound,
  DashboardSummary,
  RaceDetail,
  RaceStats,
} from "./types";

/** Calendar needs no ingestion — safe to call against an empty database. */
export function getCalendar(year: number): Promise<CalendarRound[]> {
  return request<CalendarRound[]>(`/api/seasons/${year}/calendar`);
}

export function getDashboard(year: number): Promise<DashboardSummary> {
  return request<DashboardSummary>(`/api/dashboard?season=${year}`);
}

export function getRace(raceId: string): Promise<RaceDetail> {
  return request<RaceDetail>(`/api/races/${encodeURIComponent(raceId)}`);
}

export function getRaceStats(raceId: string): Promise<RaceStats> {
  return request<RaceStats>(`/api/races/${encodeURIComponent(raceId)}/stats`);
}
