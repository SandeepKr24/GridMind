"use client";

import type { BarSeries } from "@/lib/chartFromTable";

/**
 * Horizontal bars for a single measure. Each bar carries its value as text, so
 * nothing depends on colour or bar length alone. Negative values grow left.
 */
export function ChatBars({ series }: { series: BarSeries }) {
  const max = Math.max(...series.points.map((p) => Math.abs(p.value)), 1);
  const hasNegative = series.points.some((p) => p.value < 0);

  return (
    <figure className="m-0 mt-4">
      <figcaption className="gm-label mb-2.5">
        {series.valueColumn} by {series.labelColumn}
      </figcaption>
      <div className="flex flex-col gap-1.5">
        {series.points.map((point, i) => {
          const width = (Math.abs(point.value) / max) * (hasNegative ? 50 : 100);
          const negative = point.value < 0;
          const colour = negative ? "#FF6A6A" : i === 0 ? "#E8112D" : "#3A4049";
          return (
            <div key={`${point.label}-${i}`} className="flex items-center gap-3">
              <div className="w-[88px] shrink-0 truncate font-mono text-[11px] text-ink-muted">
                {point.label}
              </div>
              <div className="relative h-3.5 flex-1 bg-surface-inset">
                {hasNegative ? (
                  <div
                    aria-hidden="true"
                    className="absolute bottom-0 left-1/2 top-0 w-px bg-line-strong"
                  />
                ) : null}
                <div
                  className="absolute bottom-0 top-0 animate-bar"
                  style={{
                    background: colour,
                    transformOrigin: negative ? "right" : "left",
                    left: negative ? undefined : hasNegative ? "50%" : 0,
                    right: negative ? "50%" : undefined,
                    width: `${width}%`,
                    animationDelay: `${i * 70}ms`,
                  }}
                />
              </div>
              <div className="w-12 shrink-0 text-right font-mono text-xs text-ink-muted">
                {point.display}
              </div>
            </div>
          );
        })}
      </div>
    </figure>
  );
}
