// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IngestionJob, JobStage, JobStatus } from "@/lib/api/types";

vi.mock("@/lib/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/jobs")>();
  return { ...actual, getJob: vi.fn() };
});

import { getJob } from "@/lib/api/jobs";
import { ApiError } from "@/lib/api/client";
import { useIngestionJob } from "./useIngestionJob";

const getJobMock = vi.mocked(getJob);

function job(stage: JobStage, status: JobStatus = "running", extra: Partial<IngestionJob> = {}): IngestionJob {
  return {
    id: "job_1",
    status,
    stage,
    progress_percent: null,
    season_year: 2025,
    round_number: 14,
    session_type: "race",
    started_at: null,
    finished_at: null,
    error_message: null,
    rows_written: null,
    ...extra,
  };
}

/** Let the pending poll resolve, then move the clock to the next poll. */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  getJobMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useIngestionJob", () => {
  it("does nothing without a job id", () => {
    const { result } = renderHook(() => useIngestionJob(null));

    expect(result.current.isActive).toBe(false);
    expect(getJobMock).not.toHaveBeenCalled();
  });

  it("follows the stage the backend reports and logs each change once", async () => {
    getJobMock
      .mockResolvedValueOnce(job("resolving"))
      .mockResolvedValueOnce(job("fetching"))
      .mockResolvedValueOnce(job("fetching"))
      .mockResolvedValueOnce(job("storing"));

    const { result } = renderHook(() => useIngestionJob("job_1"));

    await tick(0);
    expect(result.current.stage).toBe("resolving");
    expect(result.current.stageIndex).toBe(0);
    expect(result.current.isActive).toBe(true);

    await tick(1500);
    await tick(1500);
    await tick(1500);

    expect(result.current.stage).toBe("storing");
    expect(result.current.stageIndex).toBe(2);
    expect(result.current.log.map((l) => l.text)).toEqual([
      "Resolving the session",
      "Fetching timing data",
      "Storing results and laps",
    ]);
  });

  it("never advances a stage on its own while the backend is still on it", async () => {
    getJobMock.mockResolvedValue(job("fetching"));

    const { result } = renderHook(() => useIngestionJob("job_1"));
    await tick(60_000);

    expect(result.current.stage).toBe("fetching");
    expect(result.current.elapsedSeconds).toBeGreaterThanOrEqual(59);
  });

  it("stops polling and reports success once, when the job finishes", async () => {
    getJobMock
      .mockResolvedValueOnce(job("answering"))
      .mockResolvedValueOnce(job("answering", "succeeded"));
    const onComplete = vi.fn();

    const { result } = renderHook(() => useIngestionJob("job_1", onComplete));
    await tick(0);
    await tick(1500);
    await tick(10_000);

    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith(true);
    expect(getJobMock).toHaveBeenCalledTimes(2);
    expect(result.current.isActive).toBe(false);
  });

  it("treats a cached session as success", async () => {
    getJobMock.mockResolvedValueOnce(job("answering", "skipped_cached"));
    const onComplete = vi.fn();

    renderHook(() => useIngestionJob("job_1", onComplete));
    await tick(0);

    expect(onComplete).toHaveBeenCalledWith(true);
  });

  it("surfaces a failed job with the backend's message", async () => {
    getJobMock.mockResolvedValueOnce(
      job("fetching", "failed", { error_message: "Timing API unavailable" })
    );
    const onComplete = vi.fn();

    const { result } = renderHook(() => useIngestionJob("job_1", onComplete));
    await tick(0);

    expect(onComplete).toHaveBeenCalledWith(false);
    expect(result.current.isFailed).toBe(true);
    expect(result.current.error).toBe("Timing API unavailable");
    expect(result.current.log.at(-1)?.text).toBe("Timing API unavailable");
  });

  it("keeps polling through a transient error and shows it meanwhile", async () => {
    getJobMock
      .mockRejectedValueOnce(new ApiError("network", "Could not reach the backend."))
      .mockResolvedValueOnce(job("storing"));

    const { result } = renderHook(() => useIngestionJob("job_1"));
    await tick(0);
    expect(result.current.error).toBe("Could not reach the backend.");

    await tick(1500);
    expect(result.current.error).toBeNull();
    expect(result.current.stage).toBe("storing");
  });

  it("marks a long-running job overdue without calling it failed", async () => {
    getJobMock.mockResolvedValue(job("fetching"));

    const { result } = renderHook(() => useIngestionJob("job_1"));
    await tick(149_000);
    expect(result.current.isOverdue).toBe(false);

    await tick(2_000);
    expect(result.current.isOverdue).toBe(true);
    expect(result.current.isFailed).toBe(false);
  });

  it("measures elapsed time from the backend's start time after a refresh", async () => {
    const startedAt = new Date(Date.now() - 90_000).toISOString();
    getJobMock.mockResolvedValue(job("fetching", "running", { started_at: startedAt }));

    const { result } = renderHook(() => useIngestionJob("job_1"));
    await tick(500);

    expect(result.current.elapsedSeconds).toBeGreaterThanOrEqual(90);
  });

  it("resets when the job id changes", async () => {
    getJobMock.mockResolvedValue(job("storing"));

    const { result, rerender } = renderHook(({ id }) => useIngestionJob(id), {
      initialProps: { id: "job_1" as string | null },
    });
    await tick(0);
    expect(result.current.log).toHaveLength(1);

    rerender({ id: null });
    expect(result.current.log).toHaveLength(0);
    expect(result.current.isActive).toBe(false);
  });
});
