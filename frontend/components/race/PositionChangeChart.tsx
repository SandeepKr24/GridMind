"use client";

import { useState } from "react";
import type { PositionChange } from "@/lib/api/types";
import { AXIS_COLOUR, GAIN_COLOUR, LOSS_COLOUR } from "@/lib/charts";
import { useElementWidth } from "@/lib/hooks/useElementWidth";
import { EmptyState } from "@/components/ui/primitives";
import { ChartTooltip, type TooltipState } from "./ChartTooltip";

const signed = (n: number) => (n > 0 ? `+${n}` : String(n));

/**
 * Places gained or lost from grid to flag. Bars grow from one centre line:
 * gains right in blue, losses left in red, a warm/cool pair that stays apart
 * for colour-blind readers. Every bar also carries its signed value as text.
 */
export function PositionChangeChart({ changes }: { changes: PositionChange[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(480);
  const [tip, setTip] = useState<TooltipState | null>(null);

  if (changes.length === 0) {
    return (
      <EmptyState title="No position data" body="Grid and finishing positions are not available for this session." />
    );
  }

  const maxDelta = Math.max(1, ...changes.map((c) => Math.abs(c.positions_gained)));

  // Open on the empty side of the zero line: left for gains, right for losses.
  const show = (c: PositionChange, row: HTMLElement) =>
    setTip({
      x: c.positions_gained > 0 ? 40 : width - 40,
      y: row.offsetTop,
      title: c.driver_name,
      rows: [
        { label: "grid", value: `P${c.grid_position}` },
        { label: "finish", value: `P${c.finish_position}` },
        { label: c.positions_gained >= 0 ? "places gained" : "places lost", value: signed(c.positions_gained) },
      ],
    });

  return (
    <div>
      <div className="mb-3 flex gap-5">
        {[
          ["Gained", GAIN_COLOUR],
          ["Lost", LOSS_COLOUR],
        ].map(([label, colour]) => (
          <div key={label} className="flex items-center gap-2">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ background: colour }} />
            <span className="text-sm text-ink-muted">{label}</span>
          </div>
        ))}
      </div>

      <div ref={ref} className="relative" onPointerLeave={() => setTip(null)}>
        {changes.map((c, i) => {
          const gained = c.positions_gained > 0;
          const barWidth = (Math.abs(c.positions_gained) / maxDelta) * 50;
          return (
            <div
              key={c.driver_code}
              className="group flex h-7 items-center gap-3 rounded-sm transition-colors hover:bg-surface-hover/60"
              onPointerEnter={(event) => show(c, event.currentTarget)}
            >
              <div className="w-[44px] shrink-0 pl-1 font-mono text-xs text-ink-muted group-hover:text-ink">
                {c.driver_code}
              </div>
              <div className="relative h-full flex-1">
                <div aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px" style={{ background: AXIS_COLOUR }} />
                {c.positions_gained !== 0 ? (
                  <div
                    className="absolute inset-y-0 my-auto h-3 animate-bar"
                    style={{
                      background: gained ? GAIN_COLOUR : LOSS_COLOUR,
                      transformOrigin: gained ? "left" : "right",
                      left: gained ? "50%" : undefined,
                      right: gained ? undefined : "50%",
                      width: `${barWidth}%`,
                      // Rounded at the data end, square on the centre line.
                      borderRadius: gained ? "0 4px 4px 0" : "4px 0 0 4px",
                      animationDelay: `${i * 25}ms`,
                    }}
                  />
                ) : null}
              </div>
              <div className="w-9 shrink-0 pr-1 text-right font-mono text-xs tabular-nums text-ink-muted group-hover:text-ink">
                {signed(c.positions_gained)}
              </div>
            </div>
          );
        })}
        <ChartTooltip tip={tip} containerWidth={width} />
      </div>
    </div>
  );
}
