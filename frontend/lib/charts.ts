/**
 * Chart maths shared by the race charts: scales, ticks and ordering. Kept out
 * of the components so it can be tested without rendering anything.
 */

/**
 * Driver colours for the lap pace chart, in fixed slot order: winner, second,
 * third. Validated on the panel surface (#0E1013) with the dataviz palette
 * checker, all pairs, since lines cross: worst colour-blind separation
 * ΔE 9.4, normal vision ΔE 20.9, every slot above 3:1 contrast.
 */
export const SERIES_COLOURS = ["#3987e5", "#d95926", "#199e70"] as const;

/** Positions gained vs lost: opposite warm/cool poles (colour-blind ΔE 19.2). */
export const GAIN_COLOUR = "#3987e5";
export const LOSS_COLOUR = "#e66767";

/** Chart chrome: one step off the panel surface, hairline weight. */
export const GRID_COLOUR = "#1D2126";
export const AXIS_COLOUR = "#2A2F36";

export function formatLapTime(ms: number, { axis = false }: { axis?: boolean } = {}): string {
  const minutes = Math.floor(ms / 60_000);
  const seconds = (ms % 60_000) / 1000;
  if (!axis) return `${minutes}:${seconds.toFixed(3).padStart(6, "0")}`;
  // Axis labels drop trailing zeros: 1:46, 1:46.5.
  const trimmed = Number(seconds.toFixed(1));
  const whole = Number.isInteger(trimmed);
  return `${minutes}:${(whole ? String(trimmed) : trimmed.toFixed(1)).padStart(whole ? 2 : 4, "0")}`;
}

function quantile(sorted: number[], q: number): number {
  const index = (sorted.length - 1) * q;
  const low = Math.floor(index);
  const high = Math.ceil(index);
  return sorted[low]! + (sorted[high]! - sorted[low]!) * (index - low);
}

/**
 * The lap-time range to plot. Pit, safety-car and first laps are far slower
 * than racing laps; scaling to them squashes every racing lap into a thin
 * band. So the top of the range is the usual outlier fence (upper quartile
 * plus 1.5 interquartile ranges): a heavy-fuel early lap stays in, an in-lap
 * or out-lap does not. A percentile cut failed here, since two stops per
 * driver already make over 10% of laps slow ones. Slower laps are clipped off
 * the top, and `clipped` says whether any were, so the chart can say so.
 */
export function paceDomain(times: number[]): { min: number; max: number; clipped: boolean } {
  const sorted = [...times].sort((a, b) => a - b);
  const fastest = sorted[0]!;
  const slowest = sorted[sorted.length - 1]!;
  const q1 = quantile(sorted, 0.25);
  const q3 = quantile(sorted, 0.75);
  const cap = q3 + Math.max(500, 1.5 * (q3 - q1));
  const max = Math.min(slowest, cap);
  const pad = Math.max(250, (max - fastest) * 0.06);
  return { min: fastest - pad, max: max + pad, clipped: slowest > cap };
}

// No step below 0.5s: axis labels carry one decimal at most.
const TIME_STEPS = [500, 1000, 2000, 5000, 10_000, 30_000];

/** Round lap-time gridlines inside the range, aiming for three to five. */
export function timeTicks(min: number, max: number): number[] {
  const step = TIME_STEPS.find((s) => (max - min) / s <= 5) ?? TIME_STEPS[TIME_STEPS.length - 1]!;
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) ticks.push(t);
  return ticks;
}

/**
 * Lap axis labels: lap 1, round laps, and the final lap. `minGap` (in laps)
 * is the space a label needs at the chart's current width, so a round-lap
 * label that would touch the final one is dropped on narrow screens.
 */
export function lapTicks(lastLap: number, minGap = 0): number[] {
  const step = lastLap > 30 ? 10 : 5;
  const ticks = [1];
  for (let lap = step; lap < lastLap; lap += step) {
    // Too close to the final lap label, which is always shown.
    if (lastLap - lap >= Math.max(step * 0.3, minGap)) ticks.push(lap);
  }
  if (lastLap > 1) ticks.push(lastLap);
  return ticks;
}

/** Sort rows by finishing order; drivers not in it keep their order at the end. */
export function orderByFinish<T extends { driver_code: string }>(items: T[], finish: string[]): T[] {
  const rank = new Map(finish.map((code, i) => [code, i]));
  return items
    .map((item, i) => ({ item, key: rank.get(item.driver_code) ?? finish.length + i }))
    .sort((a, b) => a.key - b.key)
    .map(({ item }) => item);
}
