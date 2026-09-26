// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/* ---------- Navigation: a tiny URL store, so a replace() re-renders ---------- */

const nav = vi.hoisted(() => {
  let search = "";
  const listeners = new Set<() => void>();
  return {
    params: { id: "2025-14" },
    replaced: [] as string[],
    get search() {
      return search;
    },
    setSearch(next: string) {
      search = next;
      listeners.forEach((l) => l());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
});

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useParams: () => nav.params,
    usePathname: () => "/page",
    useRouter: () => ({
      replace: (href: string) => {
        nav.replaced.push(href);
        nav.setSearch(href.split("?")[1] ?? "");
      },
    }),
    useSearchParams: () =>
      new URLSearchParams(
        useSyncExternalStore(nav.subscribe, () => nav.search, () => nav.search)
      ),
  };
});

vi.mock("next/link", async () => {
  const { createElement } = await import("react");
  return {
    default: ({ href, children, ...rest }: { href: string; children: ReactNode }) =>
      createElement("a", { href, ...rest }, children),
  };
});

/* ---------- API ---------- */

vi.mock("@/lib/api/races", () => ({
  getDashboard: vi.fn(),
  getCalendar: vi.fn(),
  getRace: vi.fn(),
  getRaceStats: vi.fn(),
}));
vi.mock("@/lib/api/reports", () => ({
  getRaceReport: vi.fn(),
  getReport: vi.fn(),
  generateReport: vi.fn(),
}));
vi.mock("@/lib/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/jobs")>();
  return { ...actual, getJob: vi.fn(), triggerIngest: vi.fn() };
});
vi.mock("@/lib/api/chat", () => ({ sendChatMessage: vi.fn() }));

import { getCalendar, getDashboard, getRace, getRaceStats } from "@/lib/api/races";
import { generateReport, getRaceReport, getReport } from "@/lib/api/reports";
import { getJob, triggerIngest } from "@/lib/api/jobs";
import { sendChatMessage } from "@/lib/api/chat";
import { ApiError } from "@/lib/api/client";
import type {
  ChatResponse,
  IngestionJob,
  RaceDetail,
  RaceStats,
  Report,
} from "@/lib/api/types";
import { SettingsProvider } from "@/components/SettingsProvider";
import { AppShell } from "@/components/AppShell";
import DashboardPage from "./page";
import RacesPage from "./races/page";
import RaceDetailPage from "./races/[id]/page";
import ReportPage from "./reports/[id]/page";
import ChatPage from "./chat/page";

const api = {
  getDashboard: vi.mocked(getDashboard),
  getCalendar: vi.mocked(getCalendar),
  getRace: vi.mocked(getRace),
  getRaceStats: vi.mocked(getRaceStats),
  getRaceReport: vi.mocked(getRaceReport),
  getReport: vi.mocked(getReport),
  generateReport: vi.mocked(generateReport),
  getJob: vi.mocked(getJob),
  triggerIngest: vi.mocked(triggerIngest),
  sendChatMessage: vi.mocked(sendChatMessage),
};

/* ---------- Fixtures ---------- */

const race = (extra: Partial<RaceDetail> = {}): RaceDetail => ({
  id: "2025-14",
  season: 2025,
  round: 14,
  event_name: "Italian Grand Prix",
  circuit_name: "Monza",
  event_date: "07 SEP",
  state: "ingested",
  winner_name: "Lando Norris",
  has_report: false,
  total_laps: 53,
  fastest_lap_time: "1:21.0",
  fastest_lap_driver: "NOR",
  safety_car_periods: 1,
  winning_margin: "1.2s",
  ...extra,
});

const stats: RaceStats = {
  classification: [
    {
      position: 1,
      driver_name: "Lando Norris",
      driver_code: "NOR",
      constructor_name: "McLaren",
      grid_position: 2,
      points: 25,
      status: "Finished",
      best_lap_time: "1:21.0",
      pit_stop_count: 1,
      gap_to_leader: null,
    },
  ],
  position_changes: [],
  pace_traces: [],
  strategies: [],
  pit_stops: [],
  race_control: [],
};

const report: Report = {
  id: "r1",
  race_id: "2025-14",
  event_name: "Italian Grand Prix",
  season: 2025,
  report_type: "race_report",
  generated_at: "2025-09-07T16:00:00Z",
  model: "test-model",
  trigger: "on_request",
  sections: [
    { heading: "SUMMARY", body: "Norris controlled the race." },
    { heading: "STRATEGY", body: "One stop was enough." },
    { heading: "TAKEAWAYS", body: "McLaren had the pace." },
  ],
};

const job = (status: IngestionJob["status"], extra: Partial<IngestionJob> = {}): IngestionJob => ({
  id: "j1",
  status,
  stage: "resolving",
  progress_percent: null,
  season_year: 2025,
  round_number: 14,
  session_type: "race",
  started_at: null,
  finished_at: null,
  error_message: null,
  rows_written: null,
  ...extra,
});

const answer = (extra: Partial<ChatResponse> = {}): ChatResponse => ({
  answer: "Norris gained the most positions.",
  data: [],
  table: { columns: ["DRIVER", "GAINED"], rows: [["NOR", "5"], ["LEC", "2"]] },
  sources: ["classification"],
  query_type: "position_changes",
  resolved_entities: {
    year: 2025,
    round: 14,
    grand_prix: "Italian Grand Prix",
    session_type: "race",
    drivers: [],
  },
  ingestion: null,
  needs_clarification: false,
  clarifying_question: null,
  conversation_id: "c1",
  ...extra,
});

const notFound = () => new ApiError("not_found", "Not found", 404);

const renderPage = (ui: ReactNode) => render(<SettingsProvider>{ui}</SettingsProvider>);

beforeEach(() => {
  nav.setSearch("");
  nav.replaced.length = 0;
  nav.params = { id: "2025-14" };
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  Object.values(api).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/* ---------- Dashboard ---------- */

describe("Dashboard", () => {
  const summary = {
    season: 2026,
    rounds_ingested: 0,
    rounds_on_calendar: 24,
    laps_stored: 0,
    reports_written: 0,
    average_cold_fetch_seconds: null,
    latest_race: null,
    latest_podium: [],
    latest_report: null,
  };

  it("asks for the selected season and shows honest empty states", async () => {
    api.getDashboard.mockResolvedValue(summary);
    renderPage(<DashboardPage />);

    expect(await screen.findByText("No results yet")).toBeTruthy();
    expect(screen.getByText("No report yet")).toBeTruthy();
    expect(screen.getByText("of 24 on the calendar")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
    expect(api.getDashboard).toHaveBeenCalledWith(new Date().getFullYear());
  });

  it("shows the latest podium and report", async () => {
    api.getDashboard.mockResolvedValue({
      ...summary,
      rounds_ingested: 1,
      average_cold_fetch_seconds: 74.4,
      latest_race: race(),
      latest_podium: stats.classification,
      latest_report: report,
    });
    renderPage(<DashboardPage />);

    expect(await screen.findByText("Lando Norris")).toBeTruthy();
    expect(screen.getByText("74s")).toBeTruthy();
    expect(screen.getByText("READ REPORT").closest("a")?.getAttribute("href")).toBe("/reports/r1");
  });

  it("explains when the backend is unreachable", async () => {
    api.getDashboard.mockRejectedValue(new ApiError("network", "down"));
    renderPage(<DashboardPage />);
    expect(await screen.findByText("NO CONNECTION TO THE BACKEND")).toBeTruthy();
  });
});

/* ---------- Races ---------- */

describe("Races", () => {
  it("links ingested and available rounds, but not upcoming ones", async () => {
    api.getCalendar.mockResolvedValue([
      { season: 2025, round: 14, event_name: "Italian Grand Prix", circuit_name: "Monza", country: "Italy", event_date: "07 SEP", state: "ingested", total_laps: 53 },
      { season: 2025, round: 15, event_name: "Azerbaijan Grand Prix", circuit_name: "Baku", country: null, event_date: "21 SEP", state: "available", total_laps: null },
      { season: 2025, round: 16, event_name: "Singapore Grand Prix", circuit_name: "Marina Bay", country: null, event_date: "05 OCT", state: "upcoming", total_laps: null },
    ]);
    renderPage(<RacesPage />);

    expect((await screen.findByText("Italian Grand Prix")).closest("a")?.getAttribute("href")).toBe("/races/2025-14");
    expect(screen.getByText("Azerbaijan Grand Prix").closest("a")).toBeTruthy();
    expect(screen.getByText("Singapore Grand Prix").closest("a")).toBeNull();
  });

  it("has an empty state", async () => {
    api.getCalendar.mockResolvedValue([]);
    renderPage(<RacesPage />);
    expect(await screen.findByText("No calendar available")).toBeTruthy();
  });
});

/* ---------- Race detail ---------- */

describe("Race detail", () => {
  it("fetches an un-ingested session through the Loading Pit, then shows it", async () => {
    api.getRace.mockResolvedValueOnce(race({ state: "available" })).mockResolvedValue(race());
    api.triggerIngest.mockResolvedValue({ job_id: "j1" });
    api.getJob.mockResolvedValue(job("succeeded", { stage: "answering" }));
    api.getRaceStats.mockResolvedValue(stats);
    api.getRaceReport.mockRejectedValue(notFound());
    renderPage(<RaceDetailPage />);

    fireEvent.click(await screen.findByText("Fetch this session"));

    await waitFor(() =>
      expect(api.triggerIngest).toHaveBeenCalledWith({ year: 2025, round: 14, session: "race" })
    );
    expect(nav.replaced).toContain("/page?job=j1");
    expect(await screen.findByText("Classification")).toBeTruthy();
    expect(api.getRace).toHaveBeenCalledTimes(2);
    expect(nav.search).toBe(""); // job cleared from the URL once done
  });

  it("links every section tab to a section that exists on the page", async () => {
    api.getRace.mockResolvedValue(race());
    api.getRaceStats.mockResolvedValue(stats);
    api.getRaceReport.mockRejectedValue(notFound());
    renderPage(<RaceDetailPage />);
    await screen.findByText("Classification");

    const tabs = within(screen.getByRole("navigation", { name: "Sections" })).getAllByRole("link");
    expect(tabs.length).toBeGreaterThan(0);
    for (const tab of tabs) {
      const target = tab.getAttribute("href")!.slice(1);
      expect(document.getElementById(target), `#${target}`).not.toBeNull();
    }
  });

  describe("section tabs", () => {
    async function openTabs() {
      api.getRace.mockResolvedValue(race());
      api.getRaceStats.mockResolvedValue(stats);
      api.getRaceReport.mockRejectedValue(notFound());
      const scrolled: { id: string; options: ScrollIntoViewOptions }[] = [];
      // jsdom has no layout, so record the scroll requests instead.
      Element.prototype.scrollIntoView = vi.fn(function (this: Element, options) {
        scrolled.push({ id: this.id, options: options as ScrollIntoViewOptions });
      });
      renderPage(<RaceDetailPage />);
      await screen.findByText("Classification");
      const nav = screen.getByRole("navigation", { name: "Sections" });
      return { nav, scrolled };
    }

    it("scroll smoothly to the section and put it in the address bar", async () => {
      const { nav, scrolled } = await openTabs();

      fireEvent.click(within(nav).getByText("STRATEGY"));

      expect(scrolled).toEqual([{ id: "strategy", options: { behavior: "smooth", block: "start" } }]);
      expect(window.location.hash).toBe("#strategy");
    });

    it("jump without animating when the user prefers reduced motion", async () => {
      vi.stubGlobal("matchMedia", () => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }));
      const { nav, scrolled } = await openTabs();

      fireEvent.click(within(nav).getByText("PACE"));

      expect(scrolled).toEqual([{ id: "pace", options: { behavior: "auto", block: "start" } }]);
    });

    it("stay pinned under the site header while the page scrolls", async () => {
      const { nav } = await openTabs();
      expect(nav.className).toContain("sticky");
    });
  });

  it("reattaches to a job already in the URL after a refresh", async () => {
    nav.setSearch("job=j9");
    api.getRace.mockResolvedValue(race({ state: "available" }));
    api.getJob.mockResolvedValue(job("running", { id: "j9", stage: "fetching" }));
    renderPage(<RaceDetailPage />);

    expect(await screen.findByText("Fetching timing data...")).toBeTruthy();
    expect(api.getJob).toHaveBeenCalledWith("j9");
  });

  it("shows a failed job, and dismissing it clears the job", async () => {
    nav.setSearch("job=j1");
    api.getRace.mockResolvedValue(race({ state: "available" }));
    api.getJob.mockResolvedValue(job("failed", { stage: "fetching", error_message: "Timing API unavailable" }));
    renderPage(<RaceDetailPage />);

    expect(await screen.findByText("JOB FAILED")).toBeTruthy();
    fireEvent.click(screen.getByText("DISMISS"));
    await waitFor(() => expect(screen.queryByText("JOB FAILED")).toBeNull());
    expect(nav.search).toBe("");
  });

  it("explains when the fetch cannot start", async () => {
    api.getRace.mockResolvedValue(race({ state: "available" }));
    api.triggerIngest.mockRejectedValue(new ApiError("rate_limited", "slow down", 429, 20));
    renderPage(<RaceDetailPage />);

    fireEvent.click(await screen.findByText("Fetch this session"));
    expect(await screen.findByText("COULD NOT START THE FETCH")).toBeTruthy();
    expect(screen.getByText(/about 20s/)).toBeTruthy();
  });

  it("does not offer a fetch for a race that has not happened", async () => {
    api.getRace.mockResolvedValue(race({ state: "upcoming" }));
    renderPage(<RaceDetailPage />);
    expect(await screen.findByText("Not yet raced")).toBeTruthy();
    expect(screen.queryByText("Fetch this session")).toBeNull();
  });

  it("generates a missing report through a job, then shows it", async () => {
    api.getRace.mockResolvedValue(race());
    api.getRaceStats.mockResolvedValue(stats);
    api.getRaceReport.mockRejectedValueOnce(notFound()).mockResolvedValue(report);
    api.generateReport.mockResolvedValue({ job_id: "rj1" });
    api.getJob.mockResolvedValue(job("succeeded", { id: "rj1", stage: "answering" }));
    renderPage(<RaceDetailPage />);

    fireEvent.click(await screen.findByText("Generate race report"));

    expect(await screen.findByText("Norris controlled the race.")).toBeTruthy();
    expect(nav.replaced).toContain("/page?reportJob=rj1");
    expect(api.getJob).toHaveBeenCalledWith("rj1");
    expect(screen.getByText("READ FULL REPORT").closest("a")?.getAttribute("href")).toBe("/reports/r1");
  });

  it("links to the chat with a question typed in", async () => {
    api.getRace.mockResolvedValue(race());
    api.getRaceStats.mockResolvedValue(stats);
    api.getRaceReport.mockRejectedValue(notFound());
    renderPage(<RaceDetailPage />);

    const link = await screen.findByText("Who gained the most positions at the 2025 Italian Grand Prix?");
    expect(link.closest("a")?.getAttribute("href")).toMatch(/^\/chat\?q=Who%20gained/);
  });

  it("shows the race header facts, with dashes when missing", async () => {
    api.getRace.mockResolvedValue(race({ state: "available", total_laps: null, winning_margin: null }));
    renderPage(<RaceDetailPage />);
    expect(await screen.findByText("Italian Grand Prix")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});

/* ---------- Report ---------- */

describe("Report", () => {
  it("shows every section and links back to the race and chat", async () => {
    nav.params = { id: "r1" };
    api.getReport.mockResolvedValue(report);
    renderPage(<ReportPage />);

    expect(await screen.findByText("McLaren had the pace.")).toBeTruthy();
    expect(screen.getByText("RACE DATA").closest("a")?.getAttribute("href")).toBe("/races/2025-14");
    expect(screen.getByText("ASK ABOUT THIS RACE").closest("a")?.getAttribute("href")).toMatch(/^\/chat\?q=/);
  });

  it("flags a report stored without sections", async () => {
    api.getReport.mockResolvedValue({ ...report, sections: [] });
    renderPage(<ReportPage />);
    expect(await screen.findByText("Empty report")).toBeTruthy();
  });

  it("shows when it was written as a readable UTC time, not a raw timestamp", async () => {
    api.getReport.mockResolvedValue(report);
    renderPage(<ReportPage />);
    expect(await screen.findByText("7 Sep 2025, 16:00 UTC")).toBeTruthy();
    expect(screen.queryByText("2025-09-07T16:00:00Z")).toBeNull();
  });

  it("shows not found", async () => {
    api.getReport.mockRejectedValue(notFound());
    renderPage(<ReportPage />);
    expect(await screen.findByText("NOTHING HERE")).toBeTruthy();
  });
});

/* ---------- Chat ---------- */

describe("Chat", () => {
  const input = () => screen.getByLabelText("Ask about a Formula 1 race") as HTMLInputElement;

  async function ask(text: string) {
    fireEvent.change(input(), { target: { value: text } });
    fireEvent.click(screen.getByText("SEND"));
  }

  it("answers with the inferred race, a chart and a table", async () => {
    api.sendChatMessage.mockResolvedValue(answer());
    renderPage(<ChatPage />);

    await ask("Who gained the most at Monza?");

    expect(await screen.findByText("Norris gained the most positions.")).toBeTruthy();
    expect(screen.getByText("2025 · Italian Grand Prix · Race")).toBeTruthy();
    expect(screen.getByText("GAINED by DRIVER")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenCalledWith("Who gained the most at Monza?", null);
  });

  it("sends a suggested question", async () => {
    api.sendChatMessage.mockResolvedValue(answer());
    renderPage(<ChatPage />);

    fireEvent.click(await screen.findByText("Who has the most points this season?"));
    await waitFor(() => expect(api.sendChatMessage).toHaveBeenCalled());
  });

  it("renders a clarifying question as a normal reply", async () => {
    api.sendChatMessage.mockResolvedValue(
      answer({ needs_clarification: true, clarifying_question: "Which year did you mean?", answer: "" })
    );
    renderPage(<ChatPage />);

    await ask("Who won at Silverstone?");
    expect(await screen.findByText("Which year did you mean?")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("waits for ingestion, then re-asks and shows the question once", async () => {
    api.sendChatMessage
      .mockResolvedValueOnce(answer({ ingestion: { required: true, job_id: "j1" } }))
      .mockResolvedValueOnce(answer());
    api.getJob.mockResolvedValue(job("succeeded", { stage: "answering" }));
    renderPage(<ChatPage />);

    await ask("Who gained the most at Monza?");

    expect(await screen.findByText("Norris gained the most positions.")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("Who gained the most at Monza?")).toHaveLength(2); // message + history
    expect(nav.replaced).toContain("/page?job=j1");
  });

  it("re-asks after ingestion in the same conversation", async () => {
    // The backend remembers the resolved race on that conversation, so the
    // re-ask skips the LLM resolver. A new conversation would pay for it again.
    api.sendChatMessage
      .mockResolvedValueOnce(
        answer({ ingestion: { required: true, job_id: "j1" }, conversation_id: "c7" })
      )
      .mockResolvedValueOnce(answer({ conversation_id: "c7" }));
    api.getJob.mockResolvedValue(job("succeeded", { stage: "answering" }));
    renderPage(<ChatPage />);

    await ask("Who gained the most at Monza?");

    await screen.findByText("Norris gained the most positions.");
    expect(api.sendChatMessage).toHaveBeenNthCalledWith(1, "Who gained the most at Monza?", null);
    expect(api.sendChatMessage).toHaveBeenNthCalledWith(2, "Who gained the most at Monza?", "c7");
  });

  it("shows a failed ingestion and retries the question", async () => {
    api.sendChatMessage
      .mockResolvedValueOnce(answer({ ingestion: { required: true, job_id: "j1" } }))
      .mockResolvedValueOnce(answer());
    api.getJob.mockResolvedValue(
      job("failed", { stage: "fetching", error_message: "Timing API unavailable" })
    );
    renderPage(<ChatPage />);

    await ask("Who won at Monza?");
    expect(await screen.findByText("JOB FAILED")).toBeTruthy();
    expect(screen.getAllByText("Timing API unavailable")).toHaveLength(2); // headline + log

    fireEvent.click(screen.getByText("RETRY JOB"));
    expect(await screen.findByText("Norris gained the most positions.")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenCalledTimes(2);
  });

  it("finishes the original question after a refresh mid-ingest", async () => {
    window.sessionStorage.setItem("gm.chat.pending.j5", "Who won at Monza?");
    nav.setSearch("job=j5");
    api.getJob.mockResolvedValue(job("succeeded", { id: "j5", stage: "answering" }));
    api.sendChatMessage.mockResolvedValue(answer());
    renderPage(<ChatPage />);

    expect(await screen.findByText("Norris gained the most positions.")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenCalledWith("Who won at Monza?", null);
    expect(window.sessionStorage.getItem("gm.chat.pending.j5")).toBeNull();
  });

  it("starts a new conversation when the backend has forgotten the old one", async () => {
    api.sendChatMessage
      .mockResolvedValueOnce(answer())
      .mockRejectedValueOnce(notFound())
      .mockResolvedValueOnce(answer({ answer: "Leclerc was second.", conversation_id: "c2" }));
    renderPage(<ChatPage />);

    await ask("First question");
    await screen.findByText("Norris gained the most positions.");
    await ask("Second question");

    expect(await screen.findByText("Leclerc was second.")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenNthCalledWith(2, "Second question", "c1");
    expect(api.sendChatMessage).toHaveBeenNthCalledWith(3, "Second question", null);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a distinct error and retries the same question", async () => {
    api.sendChatMessage
      .mockRejectedValueOnce(new ApiError("rate_limited", "slow", 429))
      .mockResolvedValueOnce(answer());
    renderPage(<ChatPage />);

    await ask("Who won?");
    expect(await screen.findByText("EASE OFF THE THROTTLE")).toBeTruthy();

    fireEvent.click(screen.getByText("TRY AGAIN"));
    expect(await screen.findByText("Norris gained the most positions.")).toBeTruthy();
    expect(api.sendChatMessage).toHaveBeenLastCalledWith("Who won?", null);
  });

  it("types in a linked question without sending it", async () => {
    nav.setSearch("q=Who%20won%20at%20Monza%3F");
    renderPage(<ChatPage />);

    await waitFor(() => expect(input().value).toBe("Who won at Monza?"));
    expect(api.sendChatMessage).not.toHaveBeenCalled();
  });
});

/* ---------- Shell ---------- */

describe("AppShell", () => {
  it("switches season and sound from the header", async () => {
    render(
      <SettingsProvider>
        <AppShell>
          <p>content</p>
        </AppShell>
      </SettingsProvider>
    );

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "2021" } });
    await waitFor(() => expect(select.value).toBe("2021"));

    const sound = screen.getByText("SOUND OFF");
    fireEvent.click(sound);
    expect(await screen.findByText("SOUND ON")).toBeTruthy();
    expect(screen.getByText("content")).toBeTruthy();
  });
});
