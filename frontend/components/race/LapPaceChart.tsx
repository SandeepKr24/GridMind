"use client";

import { useState, type KeyboardEvent, type PointerEvent } from "react";
import type { DriverPaceTrace } from "@/lib/api/types";
import {
  AXIS_COLOUR,
  GRID_COLOUR,
  SERIES_COLOURS,
  formatLapTime,
  lapTicks,
  orderByFinish,
  paceDomain,
  timeTicks,
} from "@/lib/charts";
import { useElementWidth } from "@/lib/hooks/useElementWidth";
import { EmptyState } from "@/components/ui/primitives";
import { ChartTooltip, type TooltipState } from "./ChartTooltip";

const HEIGHT = 280;
const M = { top: 12, right: 18, bottom: 30, left: 58 };
const SURFACE = "#0E1013";
/** Pixels a lap label needs so neighbouring labels never touch. */
const LABEL_ROOM = 32;

/**
 * Lap pace for the podium finishers, plotted straight from lap_time_ms with
 * no smoothing. The range fits the racing laps, so pit, safety-car and first
 * laps run off the top instead of squashing everything else flat; the note
 * under the chart says so whenever it happens.
 */
export function LapPaceChart({
  traces,
  finishOrder = [],
}: {
  traces: DriverPaceTrace[];
  /** Driver codes in finishing order, so the winner always takes the first colour. */
  finishOrder?: string[];
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(640);
  const [hoverLap, setHoverLap] = useState<number | null>(null);

  const series = orderByFinish(
    traces.filter((t) => t.laps.length > 1),
    finishOrder
  ).slice(0, SERIES_COLOURS.length);

  if (series.length === 0) {
    return (
      <EmptyState title="No lap times" body="Lap-by-lap timing is not available for this session." />
    );
  }

  const { min, max, clipped } = paceDomain(series.flatMap((t) => t.laps.map((l) => l.lap_time_ms)));
  const lastLap = Math.max(...series.flatMap((t) => t.laps.map((l) => l.lap_number)));
  const plotW = Math.max(120, width - M.left - M.right);
  const plotH = HEIGHT - M.top - M.bottom;
  const x = (lap: number) => M.left + ((lap - 1) / Math.max(1, lastLap - 1)) * plotW;
  const y = (ms: number) => M.top + ((max - ms) / (max - min)) * plotH;

  const lapAt = (clientX: number, box: DOMRect) => {
    const ratio = (clientX - box.left - M.left) / plotW;
    return Math.min(lastLap, Math.max(1, Math.round(1 + ratio * (lastLap - 1))));
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) =>
    setHoverLap(lapAt(event.clientX, event.currentTarget.getBoundingClientRect()));
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    setHoverLap((lap) => Math.min(lastLap, Math.max(1, (lap ?? lastLap) + step)));
  };

  const tip: TooltipState | null =
    hoverLap === null
      ? null
      : {
          x: x(hoverLap),
          y: M.top,
          title: `Lap ${hoverLap}`,
          rows: series
            .map((trace, i) => ({
              trace,
              colour: SERIES_COLOURS[i],
              lap: trace.laps.find((l) => l.lap_number === hoverLap),
            }))
            .filter((r) => r.lap)
            .sort((a, b) => a.lap!.lap_time_ms - b.lap!.lap_time_ms)
            .map((r) => ({ label: r.trace.driver_code, value: formatLapTime(r.lap!.lap_time_ms), colour: r.colour })),
        };

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2">
        {series.map((trace, i) => (
          <div key={trace.driver_code} className="flex items-center gap-2">
            <span aria-hidden="true" className="h-0.5 w-4 rounded-full" style={{ background: SERIES_COLOURS[i] }} />
            <span className="text-sm text-ink-muted">{trace.driver_name}</span>
          </div>
        ))}
      </div>

      <div ref={ref} className="relative">
        <svg
          width="100%"
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="img"
          aria-label={`Lap time traces for ${series.map((t) => t.driver_name).join(", ")}. Use the arrow keys to read each lap.`}
          tabIndex={0}
          className="block touch-pan-y outline-none focus-visible:outline-2 focus-visible:outline-accent"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHoverLap(null)}
          onFocus={() => setHoverLap((lap) => lap ?? lastLap)}
          onBlur={() => setHoverLap(null)}
          onKeyDown={onKeyDown}
        >
          <defs>
            <clipPath id="pace-plot">
              <rect x={M.left} y={M.top} width={plotW} height={plotH} />
            </clipPath>
          </defs>

          {timeTicks(min, max).map((t) => (
            <g key={t}>
              <line x1={M.left} x2={M.left + plotW} y1={y(t)} y2={y(t)} stroke={GRID_COLOUR} />
              <text x={M.left - 10} y={y(t)} dy="0.32em" textAnchor="end" className="fill-ink-ghost font-mono text-xs">
                {formatLapTime(t, { axis: true })}
              </text>
            </g>
          ))}

          <line x1={M.left} x2={M.left + plotW} y1={M.top + plotH} y2={M.top + plotH} stroke={AXIS_COLOUR} />
          {lapTicks(lastLap, LABEL_ROOM / (plotW / Math.max(1, lastLap - 1))).map((lap) => (
            <text key={lap} x={x(lap)} y={HEIGHT - 8} textAnchor="middle" className="fill-ink-ghost font-mono text-xs">
              {lap === lastLap ? `L${lap}` : lap}
            </text>
          ))}

          {hoverLap !== null ? (
            <line x1={x(hoverLap)} x2={x(hoverLap)} y1={M.top} y2={M.top + plotH} stroke="#3A4049" />
          ) : null}

          <g clipPath="url(#pace-plot)">
            {series.map((trace, i) => (
              <path
                key={trace.driver_code}
                data-series={trace.driver_code}
                d={trace.laps.map((l, j) => `${j ? "L" : "M"}${x(l.lap_number).toFixed(1)},${y(l.lap_time_ms).toFixed(1)}`).join("")}
                fill="none"
                stroke={SERIES_COLOURS[i]}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {series.map((trace, i) => {
              const lap = trace.laps.find((l) => l.lap_number === (hoverLap ?? -1)) ?? (hoverLap === null ? trace.laps[trace.laps.length - 1] : undefined);
              if (!lap || lap.lap_time_ms > max) return null;
              return (
                <circle
                  key={trace.driver_code}
                  cx={x(lap.lap_number)}
                  cy={y(lap.lap_time_ms)}
                  r={4}
                  fill={SERIES_COLOURS[i]}
                  stroke={SURFACE}
                  strokeWidth={2}
                />
              );
            })}
          </g>
        </svg>
        <ChartTooltip tip={tip} containerWidth={width} />
      </div>

      <p className="m-0 mt-2 text-xs text-ink-ghost">
        Lap time per lap{clipped ? ". Slower laps (pit stops, safety car, the first lap) run off the top." : "."}
      </p>
    </div>
  );
}
