"use client";

import type {
  DriverPaceTrace,
  DriverStrategy,
  PositionChange,
  TyreCompound,
} from "@/lib/api/types";
import { EmptyState } from "@/components/ui/primitives";

const COMPOUND_COLOURS: Record<TyreCompound, string> = {
  SOFT: "#E8112D",
  MEDIUM: "#FFC400",
  HARD: "#D8DCE1",
  INTERMEDIATE: "#43B02A",
  WET: "#0067AD",
};

/** Position changes. Bars diverge from a centre line: gains right, losses left. */
export function PositionChangeChart({ changes }: { changes: PositionChange[] }) {
  if (changes.length === 0) {
    return (
      <EmptyState
        title="No position data"
        body="Grid and finishing positions are not available for this session."
      />
    );
  }

  const maxDelta = Math.max(
    1,
    ...changes.map((c) => Math.abs(c.positions_gained))
  );

  return (
    <div className="flex flex-col gap-2">
      {changes.map((c) => {
        const gained = c.positions_gained >= 0;
        const width = (Math.abs(c.positions_gained) / maxDelta) * 50;
        return (
          <div key={c.driver_code} className="flex items-center gap-3">
            <div className="w-[52px] shrink-0 font-mono text-xs text-ink-muted">
              {c.driver_code}
            </div>
            <div className="relative h-5 flex-1 bg-surface-inset">
              <div
                aria-hidden="true"
                className="absolute bottom-0 left-1/2 top-0 w-px bg-line-strong"
              />
              <div
                className="absolute bottom-0 top-0 animate-bar"
                style={{
                  background: gained ? "#00D68F" : "#E8112D",
                  transformOrigin: gained ? "left" : "right",
                  left: gained ? "50%" : undefined,
                  right: gained ? undefined : "50%",
                  width: `${width}%`,
                }}
              />
            </div>
            <div
              className="w-10 shrink-0 text-right font-mono text-xs"
              style={{ color: gained ? "#00D68F" : "#FF6A6A" }}
            >
              {gained ? "+" : ""}
              {c.positions_gained}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Lap pace. Plotted straight from lap_time_ms — no smoothing, because a smoothed
 * line would misrepresent what the timing data actually says.
 */
export function LapPaceChart({ traces }: { traces: DriverPaceTrace[] }) {
  const withLaps = traces.filter((t) => t.laps.length > 1);

  if (withLaps.length === 0) {
    return (
      <EmptyState
        title="No lap times"
        body="Lap-by-lap timing is not available for this session."
      />
    );
  }

  const allTimes = withLaps.flatMap((t) => t.laps.map((l) => l.lap_time_ms));
  const maxLap = Math.max(...withLaps.flatMap((t) => t.laps.map((l) => l.lap_number)));
  const minTime = Math.min(...allTimes);
  const maxTime = Math.max(...allTimes);
  const range = Math.max(1, maxTime - minTime);

  const W = 600;
  const H = 190;
  const PAD = 12;

  const colours = ["#E8112D", "#00D68F", "#FFB800", "#6E9BFF", "#D8DCE1"];

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Lap time traces for ${withLaps.map((t) => t.driver_name).join(", ")}`}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1={0}
            x2={W}
            y1={H * f}
            y2={H * f}
            stroke="#16191E"
            strokeWidth={1}
          />
        ))}
        {withLaps.map((trace, i) => {
          const points = trace.laps
            .map((lap) => {
              const x = ((lap.lap_number - 1) / Math.max(1, maxLap - 1)) * W;
              const y =
                PAD + ((lap.lap_time_ms - minTime) / range) * (H - PAD * 2);
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ");
          return (
            <polyline
              key={trace.driver_code}
              points={points}
              fill="none"
              stroke={colours[i % colours.length]}
              strokeWidth={1.8}
              strokeLinejoin="round"
            />
          );
        })}
      </svg>

      <div className="mt-3 flex flex-wrap gap-4">
        {withLaps.map((trace, i) => (
          <div key={trace.driver_code} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="h-0.5 w-4"
              style={{ background: colours[i % colours.length] }}
            />
            <span className="font-mono text-xs text-ink-muted">
              {trace.driver_code}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Tyre strategy timeline. Stint widths are proportional to actual lap counts. */
export function TyreStrategyChart({
  strategies,
  totalLaps,
}: {
  strategies: DriverStrategy[];
  totalLaps: number | null;
}) {
  if (strategies.length === 0) {
    return (
      <EmptyState
        title="No stint data"
        body="Tyre compound and stint information is not available for this session."
      />
    );
  }

  const laps =
    totalLaps ??
    Math.max(1, ...strategies.flatMap((s) => s.stints.map((st) => st.end_lap)));

  const used = Array.from(
    new Set(strategies.flatMap((s) => s.stints.map((st) => st.compound)))
  );

  return (
    <div>
      <div className="flex flex-col gap-2">
        {strategies.map((s) => (
          <div key={s.driver_code} className="flex items-center gap-3">
            <div className="w-[52px] shrink-0 font-mono text-xs text-ink-muted">
              {s.driver_code}
            </div>
            <div className="relative h-5 flex-1 bg-surface-inset">
              {s.stints.map((stint, i) => {
                const left = ((stint.start_lap - 1) / laps) * 100;
                const width = ((stint.end_lap - stint.start_lap + 1) / laps) * 100;
                return (
                  <div
                    key={`${stint.compound}-${stint.start_lap}-${i}`}
                    title={`${stint.compound} · laps ${stint.start_lap}-${stint.end_lap}`}
                    className="absolute bottom-0 top-0 animate-bar origin-left"
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: COMPOUND_COLOURS[stint.compound],
                      animationDelay: `${i * 90}ms`,
                    }}
                  />
                );
              })}
            </div>
            <div className="w-[62px] shrink-0 text-right font-mono text-xs text-ink-ghost">
              {s.stop_count}-STOP
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-4">
        {used.map((compound) => (
          <div key={compound} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5"
              style={{ background: COMPOUND_COLOURS[compound] }}
            />
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-ghost">
              {compound}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
