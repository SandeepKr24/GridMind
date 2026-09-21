"use client";

import { useEffect, useRef, useState } from "react";
import { getJob, isJobFinished, didJobSucceed } from "@/lib/api/jobs";
import { ApiError } from "@/lib/api/client";
import {
  JOB_STAGES,
  STAGE_LABELS,
  type IngestionJob,
  type JobStage,
} from "@/lib/api/types";

/**
 * Polls an ingestion job and exposes what the Loading Pit needs.
 *
 * Design notes carried from the frontend plan:
 * - Poll every ~1.5s. The backend is one modest container, and aggressive
 *   polling is one of the few ways this UI can create real load.
 * - Stage comes from the backend. A light never advances on a timer, because a
 *   user who watches five lights fill and then waits another 40s stops trusting
 *   the interface.
 * - Elapsed time is tracked locally purely so a long fetch stage can prove it is
 *   still alive. It never drives stage progression.
 */

const POLL_INTERVAL_MS = 1500;
const ELAPSED_TICK_MS = 250;

/**
 * A cold fetch normally lands inside 30-120s. Past this point the job is still
 * running but overdue, which the UI reports differently from a failure: the job
 * may yet finish, so the right message is "taking longer", not "broken".
 */
const OVERDUE_AFTER_SECONDS = 150;

export interface JobProgress {
  job: IngestionJob | null;
  stage: JobStage;
  stageIndex: number;
  elapsedSeconds: number;
  isActive: boolean;
  isFailed: boolean;
  /** Still running, but well past a normal cold fetch. Not a failure. */
  isOverdue: boolean;
  error: string | null;
  /** Stage transitions, newest last — rendered as the Loading Pit log. */
  log: { at: string; text: string }[];
}

function formatStamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m < 10 ? "0" : ""}${m}:${s < 10 ? "0" : ""}${s}`;
}

interface JobState {
  job: IngestionJob | null;
  elapsedSeconds: number;
  error: string | null;
  log: { at: string; text: string }[];
}

const EMPTY: JobState = { job: null, elapsedSeconds: 0, error: null, log: [] };

export function useIngestionJob(
  jobId: string | null,
  onComplete?: (ok: boolean) => void
): JobProgress {
  const [state, setState] = useState<JobState>(EMPTY);

  // Reset during render when the job changes, rather than in an effect.
  const [renderedJobId, setRenderedJobId] = useState(jobId);
  if (renderedJobId !== jobId) {
    setRenderedJobId(jobId);
    setState(EMPTY);
  }

  // When the backend reports when the job started, elapsed time is measured from
  // that — so a page that reattaches after a refresh shows the true duration.
  const backendStartRef = useRef<number | null>(null);

  // Keep the callback current without restarting polling every render.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

  // Local elapsed ticker. Proves liveness during a long fetch; never drives stages.
  useEffect(() => {
    if (!jobId) return;
    backendStartRef.current = null;
    const attachedAt = Date.now();
    const timer = setInterval(() => {
      const base = backendStartRef.current ?? attachedAt;
      setState((prev) => ({
        ...prev,
        elapsedSeconds: Math.max(0, (Date.now() - base) / 1000),
      }));
    }, ELAPSED_TICK_MS);
    return () => clearInterval(timer);
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastStage: JobStage | null = null;
    let completionFired = false;
    const startedAt = Date.now();

    const appendLog = (prev: JobState, text: string) => ({
      ...prev,
      log: [
        ...prev.log,
        { at: formatStamp((Date.now() - startedAt) / 1000), text },
      ].slice(-40),
    });

    const poll = async () => {
      try {
        const next = await getJob(jobId);
        if (cancelled) return;

        if (next.started_at && backendStartRef.current === null) {
          const parsed = Date.parse(next.started_at);
          if (Number.isFinite(parsed)) backendStartRef.current = parsed;
        }

        setState((prev) => {
          let updated: JobState = { ...prev, job: next, error: null };
          if (next.stage !== lastStage) {
            updated = appendLog(updated, STAGE_LABELS[next.stage]);
          }
          if (next.status === "failed" && next.error_message) {
            updated = appendLog(updated, next.error_message);
          }
          return updated;
        });

        lastStage = next.stage;

        if (isJobFinished(next)) {
          if (!completionFired) {
            completionFired = true;
            onCompleteRef.current?.(didJobSucceed(next));
          }
          return; // stop polling
        }
      } catch (err) {
        if (cancelled) return;
        // A transient blip should not kill the job view — keep polling and let
        // the user decide what to do.
        const message =
          err instanceof ApiError ? err.message : "Lost contact with the backend.";
        setState((prev) => ({ ...prev, error: message }));
      }

      if (!cancelled) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const stage: JobStage = state.job?.stage ?? "resolving";
  const stageIndex = Math.max(0, JOB_STAGES.indexOf(stage));
  const isFailed = state.job?.status === "failed";

  const finished = state.job !== null && isJobFinished(state.job);

  return {
    job: state.job,
    stage,
    stageIndex,
    elapsedSeconds: state.elapsedSeconds,
    isActive: Boolean(jobId) && !finished,
    isFailed,
    isOverdue:
      Boolean(jobId) &&
      !finished &&
      state.elapsedSeconds > OVERDUE_AFTER_SECONDS,
    error: isFailed
      ? state.job?.error_message ?? "The ingestion job failed."
      : state.error,
    log: state.log,
  };
}
