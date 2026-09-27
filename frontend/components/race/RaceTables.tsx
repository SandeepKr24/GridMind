"use client";

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

export function PitStopTable({ stops }: { stops: PitStopRow[] }) {
  if (stops.length === 0) {
    return (
      <EmptyState
        title="No pit stops recorded"
        body="Pit stop timing is not available for this session."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[380px] border-collapse">
        <thead>
          <tr className="text-left">
            {["DRIVER", "LAP", "DURATION"].map((h) => (
              <th key={h} scope="col" className="gm-label pb-3 pr-4 font-normal">
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
export function RaceControlList({ events }: { events: RaceControlEvent[] }) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="No race control messages"
        body="Race control events are not available for this session."
      />
    );
  }

  // A race can have a hundred messages or more, so the list scrolls inside
  // its panel. Focusable, so keyboard users can scroll it too.
  return (
    <div
      role="region"
      aria-label="Race control messages"
      tabIndex={0}
      data-lenis-prevent
      className="gm-scroll-box max-h-[min(480px,60vh)] overflow-y-auto overscroll-contain"
    >
      <ol className="m-0 flex list-none flex-col gap-px bg-line-faint p-0">
        {events.map((event, i) => (
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
    </div>
  );
}
