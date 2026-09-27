/**
 * Wire types for the GridMind backend.
 *
 * These mirror the contract in F1_Race_Analyst_Backend_Plan.md section 14.
 * Nothing here is invented client-side: if the backend does not send it,
 * the UI shows an empty state rather than filling the gap.
 */

export type SessionType =
  | "practice_1"
  | "practice_2"
  | "practice_3"
  | "qualifying"
  | "sprint"
  | "sprint_qualifying"
  | "race";

export const SESSION_LABELS: Record<SessionType, string> = {
  practice_1: "Practice 1",
  practice_2: "Practice 2",
  practice_3: "Practice 3",
  qualifying: "Qualifying",
  sprint: "Sprint",
  sprint_qualifying: "Sprint Qualifying",
  race: "Race",
};

/**
 * Whether a round's timing data is already in the backend's database.
 * Drives the three-state badge on the race list.
 */
export type IngestionState = "ingested" | "available" | "upcoming";

export interface CalendarRound {
  season: number;
  round: number;
  event_name: string;
  circuit_name: string;
  country: string | null;
  event_date: string;
  state: IngestionState;
  /** Present only once the race session has been ingested. */
  total_laps: number | null;
}

export interface RaceSummary {
  id: string;
  season: number;
  round: number;
  event_name: string;
  circuit_name: string;
  event_date: string;
  state: IngestionState;
  winner_name: string | null;
  has_report: boolean;
}

export interface RaceDetail extends RaceSummary {
  total_laps: number | null;
  fastest_lap_time: string | null;
  fastest_lap_driver: string | null;
  safety_car_periods: number | null;
  winning_margin: string | null;
}

export interface ClassificationRow {
  position: number;
  driver_name: string;
  driver_code: string;
  constructor_name: string;
  grid_position: number | null;
  points: number;
  status: string;
  best_lap_time: string | null;
  pit_stop_count: number | null;
  gap_to_leader: string | null;
}

export interface PositionChange {
  driver_name: string;
  driver_code: string;
  grid_position: number;
  finish_position: number;
  positions_gained: number;
}

export interface LapPacePoint {
  lap_number: number;
  lap_time_ms: number;
}

export interface DriverPaceTrace {
  driver_code: string;
  driver_name: string;
  laps: LapPacePoint[];
}

export type TyreCompound = "SOFT" | "MEDIUM" | "HARD" | "INTERMEDIATE" | "WET";

export interface TyreStint {
  compound: TyreCompound;
  start_lap: number;
  end_lap: number;
}

export interface DriverStrategy {
  driver_name: string;
  driver_code: string;
  stop_count: number;
  stints: TyreStint[];
}

export interface PitStopRow {
  driver_name: string;
  driver_code: string;
  lap: number;
  duration_seconds: number;
}

export interface RaceControlEvent {
  lap: number | null;
  event_type: string;
  message: string;
  timestamp: string | null;
}

export interface RaceStats {
  classification: ClassificationRow[];
  position_changes: PositionChange[];
  pace_traces: DriverPaceTrace[];
  strategies: DriverStrategy[];
  pit_stops: PitStopRow[];
  race_control: RaceControlEvent[];
}

export interface ReportSection {
  heading: string;
  body: string;
}

export interface Report {
  id: string;
  race_id: string;
  event_name: string;
  season: number;
  report_type: string;
  generated_at: string;
  model: string;
  trigger: "automatic" | "on_request";
  sections: ReportSection[];
}

/* ---------- Ingestion jobs ---------- */

/**
 * Backend ingestion stages, in order. The Loading Pit binds one light to each.
 * The order matters: index in this array is the light index.
 */
export const JOB_STAGES = [
  "resolving",
  "fetching",
  "storing",
  "verifying",
  "answering",
] as const;

export type JobStage = (typeof JOB_STAGES)[number];

export const STAGE_LABELS: Record<JobStage, string> = {
  resolving: "Resolving the session",
  fetching: "Fetching timing data",
  storing: "Storing results and laps",
  verifying: "Running analytics",
  answering: "Writing your answer",
};

export type JobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped_cached";

export interface IngestionJob {
  id: string;
  status: JobStatus;
  stage: JobStage;
  progress_percent: number | null;
  season_year: number;
  round_number: number;
  session_type: SessionType;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  rows_written: number | null;
}

/* ---------- Chat ---------- */

export interface ResolvedEntities {
  year: number | null;
  round: number | null;
  grand_prix: string | null;
  session_type: SessionType | null;
  drivers: string[];
}

export interface ChatTable {
  columns: string[];
  rows: string[][];
}

export interface ChatResponse {
  answer: string;
  /** Free-form structured rows. The backend decides the shape; the UI renders it. */
  data: Record<string, string | number | null>[];
  table: ChatTable | null;
  sources: string[];
  query_type: string | null;
  resolved_entities: ResolvedEntities | null;
  ingestion: { required: boolean; job_id: string | null } | null;
  needs_clarification: boolean;
  clarifying_question: string | null;
  conversation_id: string | null;
}

/* ---------- Client-side view models ---------- */

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  entities?: ResolvedEntities | null;
  table?: ChatTable | null;
  sources?: string[];
  isClarification?: boolean;
}

export interface DashboardSummary {
  season: number;
  rounds_ingested: number;
  rounds_on_calendar: number;
  laps_stored: number;
  reports_written: number;
  average_cold_fetch_seconds: number | null;
  latest_race: RaceSummary | null;
  latest_podium: ClassificationRow[];
  latest_report: Report | null;
}

/* ---------- Current grid (GET /api/grid) ---------- */

export interface GridDriver {
  number: number;
  code: string;
  first_name: string;
  last_name: string;
  team_name: string;
  /** "#RRGGBB", or null when the source sent nothing usable. */
  team_colour: string | null;
  /** An official headshot on media.formula1.com, or null. */
  headshot_url: string | null;
}

/** The drivers of the latest race, which is the grid as it stands. */
export interface CurrentGrid {
  season: number;
  race_location: string;
  race_date: string;
  fetched_at: string | null;
  is_stale: boolean;
  drivers: GridDriver[];
}
