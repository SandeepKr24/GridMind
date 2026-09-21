import type { Page, Route } from "@playwright/test";

/**
 * Sample API responses shaped like the backend contract, used to fill pages in
 * browser tests. The values are sample data for layout only — long names and
 * full 20-driver tables, to stress the layout the way real data will.
 */

const DRIVERS: [string, string, string][] = [
  ["Lando Norris", "NOR", "McLaren"],
  ["Oscar Piastri", "PIA", "McLaren"],
  ["Charles Leclerc", "LEC", "Ferrari"],
  ["Lewis Hamilton", "HAM", "Ferrari"],
  ["George Russell", "RUS", "Mercedes"],
  ["Andrea Kimi Antonelli", "ANT", "Mercedes"],
  ["Max Verstappen", "VER", "Red Bull Racing"],
  ["Yuki Tsunoda", "TSU", "Red Bull Racing"],
  ["Alexander Albon", "ALB", "Williams"],
  ["Carlos Sainz", "SAI", "Williams"],
  ["Fernando Alonso", "ALO", "Aston Martin"],
  ["Lance Stroll", "STR", "Aston Martin"],
  ["Pierre Gasly", "GAS", "Alpine"],
  ["Franco Colapinto", "COL", "Alpine"],
  ["Esteban Ocon", "OCO", "Haas F1 Team"],
  ["Oliver Bearman", "BEA", "Haas F1 Team"],
  ["Isack Hadjar", "HAD", "Racing Bulls"],
  ["Liam Lawson", "LAW", "Racing Bulls"],
  ["Nico Hulkenberg", "HUL", "Kick Sauber"],
  ["Gabriel Bortoleto", "BOR", "Kick Sauber"],
];

const classification = DRIVERS.map(([name, code, team], i) => ({
  position: i + 1,
  driver_name: name,
  driver_code: code,
  constructor_name: team,
  grid_position: ((i * 7) % 20) + 1,
  points: [25, 18, 15, 12, 10, 8, 6, 4, 2, 1][i] ?? 0,
  status: "Finished",
  best_lap_time: `1:2${i % 3}.${(100 + i * 37) % 1000}`,
  pit_stop_count: 1 + (i % 2),
  gap_to_leader: i === 0 ? null : `+${(i * 3.412).toFixed(3)}`,
}));

const race = (state: "ingested" | "available") => ({
  id: "2025-14",
  season: 2025,
  round: 14,
  event_name: "Italian Grand Prix",
  circuit_name: "Autodromo Nazionale di Monza",
  event_date: "07 SEP 2025",
  state,
  winner_name: state === "ingested" ? "Lando Norris" : null,
  has_report: true,
  total_laps: state === "ingested" ? 53 : null,
  fastest_lap_time: state === "ingested" ? "1:20.901" : null,
  fastest_lap_driver: "PIA",
  safety_car_periods: state === "ingested" ? 1 : null,
  winning_margin: state === "ingested" ? "1.873s" : null,
});

const stats = {
  classification,
  position_changes: classification.slice(0, 8).map((c) => ({
    driver_name: c.driver_name,
    driver_code: c.driver_code,
    grid_position: c.grid_position,
    finish_position: c.position,
    positions_gained: c.grid_position - c.position,
  })),
  pace_traces: classification.slice(0, 2).map((c, d) => ({
    driver_code: c.driver_code,
    driver_name: c.driver_name,
    laps: Array.from({ length: 53 }, (_, i) => ({
      lap_number: i + 1,
      lap_time_ms: 83_000 + d * 300 + Math.round(Math.sin(i / 3) * 400) + (i === 20 ? 20_000 : 0),
    })),
  })),
  strategies: classification.slice(0, 8).map((c, i) => ({
    driver_name: c.driver_name,
    driver_code: c.driver_code,
    stop_count: c.pit_stop_count,
    stints:
      c.pit_stop_count === 1
        ? [
            { compound: "MEDIUM", start_lap: 1, end_lap: 22 + i },
            { compound: "HARD", start_lap: 23 + i, end_lap: 53 },
          ]
        : [
            { compound: "SOFT", start_lap: 1, end_lap: 15 },
            { compound: "MEDIUM", start_lap: 16, end_lap: 34 },
            { compound: "HARD", start_lap: 35, end_lap: 53 },
          ],
  })),
  pit_stops: classification.slice(0, 6).map((c, i) => ({
    driver_name: c.driver_name,
    driver_code: c.driver_code,
    lap: 18 + i,
    duration_seconds: 2.3 + i * 0.11,
  })),
  race_control: [
    { lap: 1, event_type: "FLAG", message: "GREEN LIGHT - PIT EXIT OPEN", timestamp: null },
    { lap: 21, event_type: "SAFETY CAR", message: "VIRTUAL SAFETY CAR DEPLOYED", timestamp: null },
    { lap: 23, event_type: "SAFETY CAR", message: "VIRTUAL SAFETY CAR ENDING", timestamp: null },
  ],
};

const report = {
  id: "r1",
  race_id: "2025-14",
  event_name: "Italian Grand Prix",
  season: 2025,
  report_type: "race_report",
  generated_at: "2025-09-07T16:04:00Z",
  model: "sample-model",
  trigger: "automatic",
  sections: [
    { heading: "SUMMARY", body: "Sample report text used only to check layout. A real report is written by the backend from stored timing data." },
    { heading: "RACE STORY", body: "Sample paragraph. ".repeat(12) },
    { heading: "STRATEGY", body: "Sample paragraph. ".repeat(8) },
  ],
};

const calendar = [
  ["Dutch Grand Prix", "Circuit Zandvoort", "ingested"],
  ["Italian Grand Prix", "Autodromo Nazionale di Monza", "ingested"],
  ["Azerbaijan Grand Prix", "Baku City Circuit", "available"],
  ["Singapore Grand Prix", "Marina Bay Street Circuit", "available"],
  ["United States Grand Prix", "Circuit of the Americas", "upcoming"],
  ["Mexico City Grand Prix", "Autódromo Hermanos Rodríguez", "upcoming"],
].map(([event_name, circuit_name, state], i) => ({
  season: 2025,
  round: 13 + i,
  event_name,
  circuit_name,
  country: null,
  event_date: `${7 + i} SEP`,
  state,
  total_laps: null,
}));

const dashboard = {
  season: 2025,
  rounds_ingested: 2,
  rounds_on_calendar: 24,
  laps_stored: 4118,
  reports_written: 2,
  average_cold_fetch_seconds: 74,
  latest_race: race("ingested"),
  latest_podium: classification.slice(0, 3),
  latest_report: report,
};

const chatAnswer = {
  answer: "Sample answer used only to check layout. Norris gained the most positions from the grid.",
  data: [],
  table: {
    columns: ["DRIVER", "GRID", "FINISH", "GAINED"],
    rows: stats.position_changes.slice(0, 5).map((c) => [
      c.driver_name,
      String(c.grid_position),
      String(c.finish_position),
      String(c.positions_gained),
    ]),
  },
  sources: ["classification"],
  query_type: "position_changes",
  resolved_entities: { year: 2025, round: 14, grand_prix: "Italian Grand Prix", session_type: "race", drivers: [] },
  ingestion: null,
  needs_clarification: false,
  clarifying_question: null,
  conversation_id: "c1",
};

const runningJob = {
  id: "j1",
  status: "running",
  stage: "fetching",
  progress_percent: null,
  season_year: 2025,
  round_number: 15,
  session_type: "race",
  started_at: null,
  finished_at: null,
  error_message: null,
  rows_written: null,
};

export async function mockApi(page: Page, options: { raceState?: "ingested" | "available" } = {}) {
  const raceState = options.raceState ?? "ingested";
  const json = (route: Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("http://localhost:8000/**", (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/dashboard") return json(route, dashboard);
    if (/^\/api\/seasons\/\d+\/calendar$/.test(pathname)) return json(route, calendar);
    if (pathname === "/api/races/2025-14") return json(route, race(raceState));
    if (pathname === "/api/races/2025-14/stats") return json(route, stats);
    if (pathname === "/api/races/2025-14/report") return json(route, report);
    if (pathname === "/api/reports/r1") return json(route, report);
    if (pathname === "/api/chat") return json(route, chatAnswer);
    if (pathname.startsWith("/api/jobs/")) return json(route, runningJob);
    return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
}
