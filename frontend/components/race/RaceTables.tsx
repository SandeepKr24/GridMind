"use client";

import { useId, useState } from "react";
import type {
  ClassificationRow,
  PitStopRow,
  RaceControlEvent,
} from "@/lib/api/types";
import { EmptyState } from "@/components/ui/primitives";
import { TeamName } from "@/components/ui/TeamName";

export function ClassificationTable({ rows }: { rows: ClassificationRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No classification"
        body="Session results are not available for this race."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr className="text-left">
            {["POS", "DRIVER", "TEAM", "GRID", "BEST LAP", "STOPS", "GAP", "PTS"].map(
              (h) => (
                <th
                  key={h}
                  scope="col"
                  className="gm-label whitespace-nowrap pb-3 pr-4 font-normal"
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={`${row.position}-${row.driver_code}`}
              className="animate-rise border-t border-line-subtle"
              style={{ animationDelay: `${i * 35}ms` }}
            >
              <td className="py-2.5 pr-4 font-display text-lg font-bold text-accent">
                {row.position}
              </td>
              <td className="py-2.5 pr-4 font-display text-base font-semibold uppercase tracking-[0.03em]">
                {row.driver_name}
              </td>
              <td className="whitespace-nowrap py-2.5 pr-4 text-sm text-ink-faint">
                <TeamName name={row.constructor_name} />
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink-muted">
                {row.grid_position ?? "—"}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink-muted">
                {row.best_lap_time ?? "—"}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink-muted">
                {row.pit_stop_count ?? "—"}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink-muted">
                {row.gap_to_leader ?? (row.position === 1 ? "WINNER" : "—")}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink">{row.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Scrolls by itself: the race page sizes it to the position chart beside it.
 * `className` carries that sizing, so the table does not decide its own height.
 */
export function PitStopTable({
  stops,
  className = "",
}: {
  stops: PitStopRow[];
  className?: string;
}) {
  if (stops.length === 0) {
    return (
      <EmptyState
        title="No pit stops recorded"
        body="Pit stop timing is not available for this session."
      />
    );
  }

  return (
    <div
      role="region"
      aria-label="Pit stops"
      tabIndex={0}
      data-lenis-prevent
      className={`gm-scroll-box overflow-auto overscroll-contain ${className}`}
    >
      <table className="w-full min-w-[380px] border-collapse">
        <thead>
          <tr className="text-left">
            {["DRIVER", "LAP", "DURATION"].map((h) => (
              // Pinned, so the columns stay labelled while the list scrolls.
              <th
                key={h}
                scope="col"
                className="gm-label sticky top-0 z-10 bg-surface-raised pb-3 pr-4 font-normal"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stops.map((stop, i) => (
            <tr
              key={`${stop.driver_code}-${stop.lap}-${i}`}
              className="border-t border-line-subtle"
            >
              <td className="py-2.5 pr-4 font-display text-base font-semibold uppercase">
                {stop.driver_name}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink-muted">
                L{stop.lap}
              </td>
              <td className="py-2.5 pr-4 font-mono text-sm text-ink">
                {stop.duration_seconds.toFixed(2)}s
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Race control messages, verbatim from the timing feed. These are facts from the
 * stewards, so they are shown as received rather than paraphrased.
 */
type LapFilter =
  | { kind: "all" }
  | { kind: "lap"; lap: number }
  | { kind: "invalid" };

/** What the Lap box asks for. Empty means every lap. */
export function parseLapFilter(text: string, lastLap: number): LapFilter {
  const trimmed = text.trim();
  if (trimmed === "") return { kind: "all" };
  const lap = Number(trimmed);
  if (!Number.isInteger(lap) || lap < 1 || (lastLap > 0 && lap > lastLap)) {
    return { kind: "invalid" };
  }
  return { kind: "lap", lap };
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function RaceControlList({ events }: { events: RaceControlEvent[] }) {
  const [lapText, setLapText] = useState("");
  const inputId = useId();

  if (events.length === 0) {
    return (
      <EmptyState
        title="No race control messages"
        body="Race control events are not available for this session."
      />
    );
  }

  const lastLap = events.reduce((max, event) => Math.max(max, event.lap ?? 0), 0);
  const filter = parseLapFilter(lapText, lastLap);
  const shown =
    filter.kind === "all"
      ? events
      : filter.kind === "lap"
        ? events.filter((event) => event.lap === filter.lap)
        : [];

  const summary =
    filter.kind === "all"
      ? plural(events.length, "message")
      : filter.kind === "lap"
        ? `${plural(shown.length, "message")} on lap ${filter.lap}`
        : lastLap > 0
          ? `Enter a lap from 1 to ${lastLap}`
          : "Enter a whole lap number";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={inputId} className="gm-label">
          Lap
        </label>
        <input
          id={inputId}
          type="number"
          inputMode="numeric"
          min={1}
          max={lastLap > 0 ? lastLap : undefined}
          step={1}
          value={lapText}
          onChange={(event) => setLapText(event.target.value)}
          placeholder="All"
          className="w-24 border border-line-strong bg-surface-inset px-3 py-1.5 font-mono text-sm text-ink [color-scheme:dark] placeholder:text-ink-trace"
        />
        {lapText !== "" ? (
          <button
            type="button"
            onClick={() => setLapText("")}
            className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-ghost transition-colors hover:text-ink"
          >
            Show all
          </button>
        ) : null}
        <span aria-live="polite" className="ml-auto text-xs text-ink-ghost">
          {summary}
        </span>
      </div>

      {/* A race can have a hundred messages or more, so the list scrolls inside
          its panel. Focusable, so keyboard users can scroll it too. */}
      <div
        role="region"
        aria-label="Race control messages"
        tabIndex={0}
        data-lenis-prevent
        className="gm-scroll-box max-h-[min(480px,60vh)] overflow-y-auto overscroll-contain"
      >
        {shown.length === 0 ? (
          <p className="m-0 bg-surface-inset px-4 py-6 text-center text-sm text-ink-ghost">
            {filter.kind === "lap"
              ? `No race control messages on lap ${filter.lap}.`
              : "No messages to show."}
          </p>
        ) : (
          <ol className="m-0 flex list-none flex-col gap-px bg-line-faint p-0">
            {shown.map((event, i) => (
              <li key={i} className="bg-surface-inset px-4 py-3">
                <div className="flex items-baseline gap-3">
                  <span className="shrink-0 font-mono text-xs text-accent">
                    {event.lap === null ? "—" : `L${event.lap}`}
                  </span>
                  <div className="min-w-0">
                    <div className="font-display text-sm uppercase tracking-[0.1em] text-ink-dim">
                      {event.event_type}
                    </div>
                    <p className="m-0 mt-1 text-sm leading-relaxed text-ink-muted text-pretty">
                      {event.message}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
