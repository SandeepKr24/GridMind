"use client";

import { useState } from "react";
import type { DriverStrategy, TyreCompound } from "@/lib/api/types";
import { GRID_COLOUR, lapTicks, orderByFinish } from "@/lib/charts";
import { useElementWidth } from "@/lib/hooks/useElementWidth";
import { EmptyState } from "@/components/ui/primitives";
import { ChartTooltip, type TooltipState } from "./ChartTooltip";

/** Pirelli's compound colours: the convention every F1 viewer already reads. */
const COMPOUNDS: Record<TyreCompound, { colour: string; letter: string; ink: string }> = {
  SOFT: { colour: "#E8112D", letter: "S", ink: "#FFFFFF" },
  MEDIUM: { colour: "#FFC400", letter: "M", ink: "#0A0B0D" },
  HARD: { colour: "#D8DCE1", letter: "H", ink: "#0A0B0D" },
  INTERMEDIATE: { colour: "#43B02A", letter: "I", ink: "#0A0B0D" },
  WET: { colour: "#0067AD", letter: "W", ink: "#FFFFFF" },
};

/** Where the track starts: the driver code column plus its gap. */
const TRACK_LEFT = 44 + 12;
/** Room taken by the driver code and stop count columns, for sizing letters. */
const LABEL_COLUMNS = TRACK_LEFT + 64 + 12;
/** The compound letter only goes inside a stint wide enough to hold it. */
const MIN_LETTER_WIDTH = 20;

const stops = (n: number) => `${n} ${n === 1 ? "stop" : "stops"}`;

/**
 * Tyre strategy, one row per driver in finishing order. Stint lengths are
 * proportional to laps, separated by a 2px gap (the pit stop). The compound
 * letter inside each stint means colour is never the only cue.
 */
export function TyreStrategyChart({
  strategies,
  totalLaps,
  finishOrder = [],
}: {
  strategies: DriverStrategy[];
  totalLaps: number | null;
  finishOrder?: string[];
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(640);
  const [tip, setTip] = useState<TooltipState | null>(null);

  if (strategies.length === 0) {
    return (
      <EmptyState
        title="No stint data"
        body="Tyre compound and stint information is not available for this session."
      />
    );
  }

  const laps = totalLaps ?? Math.max(1, ...strategies.flatMap((s) => s.stints.map((st) => st.end_lap)));
  const trackWidth = Math.max(0, width - LABEL_COLUMNS);
  // Labels need ~32px each; drop a round lap that would touch the final one.
  const ticks = lapTicks(laps, trackWidth > 0 ? 32 / (trackWidth / laps) : 0);
  const rows = orderByFinish(strategies, finishOrder);
  const used = Array.from(new Set(strategies.flatMap((s) => s.stints.map((st) => st.compound))));

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2">
        {used.map((compound) => (
          <div key={compound} className="flex items-center gap-2">
            <CompoundBadge compound={compound} />
            <span className="text-sm text-ink-muted">{compound.charAt(0) + compound.slice(1).toLowerCase()}</span>
          </div>
        ))}
      </div>

      <div ref={ref} className="relative" onPointerLeave={() => setTip(null)}>
        {rows.map((s) => (
          <div key={s.driver_code} className="group flex h-7 items-center gap-3 rounded-sm hover:bg-surface-hover/60">
            <div className="w-[44px] shrink-0 pl-1 font-mono text-xs text-ink-muted group-hover:text-ink">
              {s.driver_code}
            </div>
            <div className="relative h-full flex-1">
              {ticks.map((lap) => (
                <div
                  key={lap}
                  aria-hidden="true"
                  className="absolute inset-y-0 w-px"
                  style={{ left: `${(lap / laps) * 100}%`, background: GRID_COLOUR }}
                />
              ))}
              {s.stints.map((stint, i) => {
                const spec = COMPOUNDS[stint.compound];
                const last = i === s.stints.length - 1;
                const share = (stint.end_lap - stint.start_lap + 1) / laps;
                const fits = share * trackWidth - 2 >= MIN_LETTER_WIDTH;
                const label = `${stint.compound}, laps ${stint.start_lap}-${stint.end_lap}`;
                return (
                  <div
                    key={`${stint.compound}-${stint.start_lap}-${i}`}
                    aria-label={label}
                    className="absolute inset-y-0 my-auto flex h-4 origin-left animate-bar items-center justify-center overflow-hidden"
                    style={{
                      left: `${((stint.start_lap - 1) / laps) * 100}%`,
                      // The 2px surface gap between stints marks the stop.
                      width: last ? `${share * 100}%` : `calc(${share * 100}% - 2px)`,
                      background: spec.colour,
                      borderRadius: last ? "0 4px 4px 0" : 0,
                      animationDelay: `${i * 90}ms`,
                    }}
                    onPointerEnter={(event) => {
                      const row = event.currentTarget.parentElement!.parentElement!;
                      setTip({
                        x: TRACK_LEFT + ((stint.start_lap - 1) / laps) * trackWidth,
                        y: row.offsetTop,
                        title: s.driver_name,
                        rows: [
                          { label: `laps ${stint.start_lap}-${stint.end_lap}`, value: stint.compound, colour: spec.colour },
                          { label: "laps on this set", value: String(stint.end_lap - stint.start_lap + 1) },
                        ],
                      });
                    }}
                  >
                    {fits ? (
                      <span aria-hidden="true" className="text-xs font-bold leading-none" style={{ color: spec.ink }}>
                        {spec.letter}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <div className="w-[64px] shrink-0 pr-1 text-right text-xs text-ink-ghost">{stops(s.stop_count)}</div>
          </div>
        ))}

        <div className="flex gap-3 pt-2" aria-hidden="true">
          <div className="w-[44px] shrink-0" />
          <div className="relative h-4 flex-1">
            {ticks.map((lap, i) => (
              <span
                key={lap}
                className="absolute font-mono text-xs text-ink-ghost"
                style={{
                  left: `${(lap / laps) * 100}%`,
                  transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)",
                }}
              >
                {lap === laps ? `L${lap}` : lap}
              </span>
            ))}
          </div>
          <div className="w-[64px] shrink-0" />
        </div>
        <ChartTooltip tip={tip} containerWidth={width} />
      </div>
    </div>
  );
}

function CompoundBadge({ compound }: { compound: TyreCompound }) {
  const spec = COMPOUNDS[compound];
  return (
    <span
      aria-hidden="true"
      className="flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold leading-none"
      style={{ background: spec.colour, color: spec.ink }}
    >
      {spec.letter}
    </span>
  );
}
