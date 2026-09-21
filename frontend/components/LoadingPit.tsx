"use client";

import { useEffect, useRef } from "react";
import { JOB_STAGES, STAGE_LABELS, type JobStage } from "@/lib/api/types";
import { useSettings } from "@/components/SettingsProvider";
import { Button } from "@/components/ui/primitives";

/**
 * The Loading Pit.
 *
 * Five start lights bound to backend ingestion stages. The single rule that
 * matters: lights advance when the backend reports a stage change, never on a
 * timer. A cold session fetch genuinely takes 30-120s, and faking progress
 * across that window is how you teach someone to distrust a progress indicator.
 *
 * The elapsed counter exists so the long `fetching` stage can prove it is alive
 * without pretending to be further along than it is.
 */

const LONG_FETCH_THRESHOLD_SECONDS = 8;

export interface LoadingPitProps {
  active: boolean;
  stage: JobStage;
  stageIndex: number;
  elapsedSeconds: number;
  failed?: boolean;
  error?: string | null;
  log?: { at: string; text: string }[];
  /** Headline override. Defaults to the current stage's message. */
  message?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  dismissLabel?: string;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m < 10 ? "0" : ""}${m}:${s < 10 ? "0" : ""}${s}`;
}

export function LoadingPit({
  active,
  stage,
  stageIndex,
  elapsedSeconds,
  failed = false,
  error,
  log = [],
  message,
  onRetry,
  onDismiss,
  dismissLabel = "RUN IN BACKGROUND",
}: LoadingPitProps) {
  const { soundEnabled, beepForStage, reducedMotion } = useSettings();
  const lastBeepedStage = useRef<number>(-1);

  // One beep per stage transition — never a loop during a long fetch.
  useEffect(() => {
    if (!active || failed) return;
    if (stageIndex === lastBeepedStage.current) return;
    lastBeepedStage.current = stageIndex;
    if (soundEnabled) {
      beepForStage(stageIndex, stageIndex === JOB_STAGES.length - 1);
    }
  }, [active, failed, stageIndex, soundEnabled, beepForStage]);

  useEffect(() => {
    if (!active) lastBeepedStage.current = -1;
  }, [active]);

  if (!active) return null;

  const isLongFetch =
    stage === "fetching" && elapsedSeconds > LONG_FETCH_THRESHOLD_SECONDS;

  const headline = failed ? "JOB FAILED" : message ?? `${STAGE_LABELS[stage]}...`;

  const subline = failed
    ? error ?? "The timing data for that session could not be retrieved."
    : isLongFetch
      ? `Large session — still fetching. Working, not frozen. ${Math.floor(elapsedSeconds)}s elapsed.`
      : `Stage ${stageIndex + 1} of ${JOB_STAGES.length} · lights advance on backend stages`;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Loading"
      className="fixed inset-0 z-[90] flex animate-fade items-center justify-center bg-surface-overlay p-5"
    >
      <div className="relative w-full max-w-[660px] overflow-hidden border border-line bg-[#0C0E11]">
        {!reducedMotion && !failed ? (
          <div
            className="absolute left-0 top-0 h-0.5 w-[30%] animate-sweep-fast bg-gradient-to-r from-transparent via-accent to-transparent"
            aria-hidden="true"
          />
        ) : null}

        <div className="flex flex-wrap items-baseline justify-between gap-3 px-[clamp(20px,4vw,34px)] pb-2.5 pt-[26px]">
          <div className="font-display text-[17px] uppercase tracking-[0.3em] text-ink">
            Loading Pit
          </div>
          <div className="font-mono text-xs tracking-[0.1em] text-ink-faint">
            T+{formatElapsed(elapsedSeconds)}
          </div>
        </div>

        <div className="flex justify-center gap-[clamp(14px,4vw,30px)] px-5 pb-[22px] pt-[26px]">
          {JOB_STAGES.map((s, i) => (
            <Light
              key={s}
              index={i}
              stageLabel={STAGE_LABELS[s]}
              done={stageIndex > i}
              active={stageIndex === i}
              failed={failed && stageIndex === i}
              reducedMotion={reducedMotion}
            />
          ))}
        </div>

        <div className="px-[clamp(20px,4vw,34px)] pb-5 text-center">
          <div
            className={`font-display text-[clamp(20px,4vw,28px)] uppercase tracking-[0.14em] ${
              failed ? "text-status-pending" : "text-ink"
            }`}
          >
            {headline}
          </div>
          <div className="mt-2 font-mono text-[11px] tracking-[0.06em] text-ink-ghost">
            {subline}
          </div>
        </div>

        {log.length > 0 ? (
          <div className="mx-[clamp(20px,4vw,34px)] flex max-h-[132px] flex-col gap-1.5 overflow-y-auto border-t border-line-faint py-3.5">
            {log.map((line, i) => (
              <div key={`${line.at}-${i}`} className="flex gap-3 font-mono text-[11px]">
                <span className="text-[#4A5058]">{line.at}</span>
                <span className="text-ink-muted">{line.text}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap justify-end gap-2.5 border-t border-line-faint px-[clamp(20px,4vw,34px)] pb-6 pt-4">
          {failed && onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="bg-accent px-5 py-2.5 font-mono text-[11px] tracking-[0.12em] text-white hover:bg-accent-bright"
            >
              RETRY JOB
            </button>
          ) : null}
          {onDismiss ? (
            <Button variant="quiet" onClick={onDismiss}>
              {failed ? "DISMISS" : dismissLabel}
            </Button>
          ) : null}
        </div>
      </div>

      {/*
        Screen readers get the stage as text. With waits over a minute, a silent
        region is an accessibility failure rather than a missing nicety.
      */}
      <div aria-live="polite" className="gm-sr-only">
        {failed ? `Loading failed. ${error ?? ""}` : STAGE_LABELS[stage]}
      </div>
    </div>
  );
}

function Light({
  index,
  stageLabel,
  done,
  active,
  failed,
  reducedMotion,
}: {
  index: number;
  stageLabel: string;
  done: boolean;
  active: boolean;
  failed: boolean;
  reducedMotion: boolean;
}) {
  const lit = done || active;
  const colour = failed ? "#FFB800" : "#E8112D";

  return (
    <div className="flex flex-col items-center gap-2.5">
      <div
        title={stageLabel}
        className="flex items-center justify-center rounded-full border-2"
        style={{
          width: "clamp(38px,9vw,56px)",
          height: "clamp(38px,9vw,56px)",
          borderColor: lit ? colour : "#23272D",
          boxShadow: lit ? "0 0 22px rgba(232,17,45,.35)" : undefined,
        }}
      >
        <div
          className={`h-[56%] w-[56%] rounded-full ${
            active && !done && !reducedMotion && !failed ? "animate-pulse" : ""
          }`}
          style={{ background: lit ? colour : "#181B20" }}
        />
      </div>
      <div className="font-mono text-[9px] tracking-[0.1em] text-ink-trace">
        {index + 1}
      </div>
    </div>
  );
}
