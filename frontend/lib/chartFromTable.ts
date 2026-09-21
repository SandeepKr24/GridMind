import type { ChatTable } from "@/lib/api/types";

/**
 * Decides whether a chat answer's table is worth a bar chart, and if so, which
 * columns to plot.
 *
 * The backend decides the data shape; the frontend decides how to show it. A
 * chart is only drawn when it adds something a table does not — a single
 * numeric measure compared across a handful of rows. Anything else stays a
 * table, per the frontend plan: "Do not create a chart when a simple table
 * communicates the data better."
 */

export interface BarPoint {
  label: string;
  value: number;
  /** The cell text as the backend sent it, shown beside the bar unchanged. */
  display: string;
}

export interface BarSeries {
  labelColumn: string;
  valueColumn: string;
  points: BarPoint[];
}

const MIN_ROWS = 2;
const MAX_ROWS = 12;
const NUMERIC = /^[+-]?\d+(\.\d+)?$/;

function parseNumeric(cell: string | undefined): number | null {
  if (cell === undefined) return null;
  const trimmed = cell.trim();
  return NUMERIC.test(trimmed) ? Number(trimmed) : null;
}

export function barSeriesFromTable(table: ChatTable | null | undefined): BarSeries | null {
  if (!table) return null;
  const { columns, rows } = table;
  if (columns.length < 2) return null;
  if (rows.length < MIN_ROWS || rows.length > MAX_ROWS) return null;

  // Prefer the rightmost fully numeric column: tables tend to end with the
  // measure the question was about ("GAINED", "POINTS").
  for (let col = columns.length - 1; col >= 1; col--) {
    const values = rows.map((row) => parseNumeric(row[col]));
    if (values.some((v) => v === null)) continue;

    const numbers = values as number[];
    if (numbers.every((v) => v === 0)) return null;

    return {
      labelColumn: columns[0] ?? "",
      valueColumn: columns[col] ?? "",
      points: rows.map((row, i) => ({
        label: row[0] ?? "",
        value: numbers[i] ?? 0,
        display: (row[col] ?? "").trim(),
      })),
    };
  }

  return null;
}
