import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({ request: vi.fn().mockResolvedValue("ok") }));

import { request } from "./client";
import { sendChatMessage } from "./chat";
import { didJobSucceed, getJob, isJobFinished, triggerIngest } from "./jobs";
import { getCalendar, getDashboard, getRace, getRaceStats } from "./races";
import { generateReport, getRaceReport, getReport } from "./reports";
import type { IngestionJob, JobStatus } from "./types";

const requestMock = vi.mocked(request);

beforeEach(() => requestMock.mockClear());

describe("endpoint paths", () => {
  it.each([
    ["getCalendar", () => getCalendar(2025), "/api/seasons/2025/calendar"],
    ["getDashboard", () => getDashboard(2025), "/api/dashboard?season=2025"],
    ["getRace", () => getRace("2025-14"), "/api/races/2025-14"],
    ["getRaceStats", () => getRaceStats("2025-14"), "/api/races/2025-14/stats"],
    ["getRaceReport", () => getRaceReport("2025-14"), "/api/races/2025-14/report"],
    ["getReport", () => getReport("r1"), "/api/reports/r1"],
  ])("%s calls %s", async (_, call, path) => {
    await call();
    expect(requestMock.mock.calls[0]?.[0]).toBe(path);
  });

  it("encodes ids so they cannot escape the path", async () => {
    await getRace("../admin?x=1");
    expect(requestMock.mock.calls[0]?.[0]).toBe("/api/races/..%2Fadmin%3Fx%3D1");
  });

  it("generateReport posts to the generate endpoint", async () => {
    await generateReport("2025-14");
    expect(requestMock).toHaveBeenCalledWith("/api/races/2025-14/report/generate", {
      method: "POST",
    });
  });

  it("triggerIngest sends the backend's field names", async () => {
    await triggerIngest({ year: 2025, round: 14, session: "race" });
    expect(requestMock).toHaveBeenCalledWith("/api/ingest", {
      method: "POST",
      body: { season_year: 2025, round_number: 14, session_type: "race" },
    });
  });

  it("triggerIngest asks for a re-ingest only when forced", async () => {
    await triggerIngest({ year: 2025, round: 14, session: "race", force: true });
    expect(requestMock).toHaveBeenCalledWith("/api/ingest", {
      method: "POST",
      body: { season_year: 2025, round_number: 14, session_type: "race", force: true },
    });
  });

  it("getJob uses a long timeout", async () => {
    await getJob("job_1");
    expect(requestMock.mock.calls[0]?.[1]).toEqual({ timeoutMs: 30_000 });
  });

  it("sendChatMessage sends the message and conversation id", async () => {
    const signal = new AbortController().signal;
    await sendChatMessage("Who won?", "c1", signal);
    expect(requestMock).toHaveBeenCalledWith("/api/chat", {
      method: "POST",
      body: { message: "Who won?", conversation_id: "c1" },
      timeoutMs: 30_000,
      signal,
    });
  });
});

describe("job status helpers", () => {
  const job = (status: JobStatus) => ({ status }) as IngestionJob;

  it.each([
    ["pending", false, false],
    ["running", false, false],
    ["succeeded", true, true],
    ["skipped_cached", true, true],
    ["failed", true, false],
  ] as const)("%s: finished=%s succeeded=%s", (status, finished, succeeded) => {
    expect(isJobFinished(job(status))).toBe(finished);
    expect(didJobSucceed(job(status))).toBe(succeeded);
  });
});
