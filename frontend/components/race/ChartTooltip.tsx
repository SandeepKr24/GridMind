/**
 * The hover readout shared by the race charts. Values lead in primary ink and
 * labels follow in muted ink; identity comes from the small mark beside each
 * row, never from coloured text. It never gates a value: the same numbers are
 * in the tables, on the axes or beside the marks.
 */

export interface TooltipRow {
  label: string;
  value: string;
  /** Series colour for the mark beside the row. */
  colour?: string;
}

export interface TooltipState {
  x: number;
  y: number;
  title: string;
  rows: TooltipRow[];
}

const WIDTH = 188;
const OFFSET = 14;

export function ChartTooltip({ tip, containerWidth }: { tip: TooltipState | null; containerWidth: number }) {
  if (!tip) return null;
  // Keep it inside the chart: flip to the left of the pointer near the right edge.
  const flip = tip.x + OFFSET + WIDTH > containerWidth;
  const left = flip ? Math.max(0, tip.x - OFFSET - WIDTH) : tip.x + OFFSET;

  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-20 border border-line-strong bg-surface-base/95 px-3 py-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.45)] backdrop-blur-sm"
      style={{ left, top: Math.max(0, tip.y - 12), width: WIDTH }}
    >
      <div className="gm-label mb-1.5">{tip.title}</div>
      <div className="flex flex-col gap-1">
        {tip.rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2 text-sm">
            {row.colour ? (
              <span
                aria-hidden="true"
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: row.colour }}
              />
            ) : null}
            <span className="font-mono font-medium tabular-nums text-ink">{row.value}</span>
            <span className="truncate text-ink-ghost">{row.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
