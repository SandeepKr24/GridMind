import { describe, expect, it } from "vitest";
import { barSeriesFromTable } from "./chartFromTable";

const table = (columns: string[], rows: string[][]) => ({ columns, rows });

describe("barSeriesFromTable", () => {
  it("plots the rightmost fully numeric column against the first column", () => {
    const series = barSeriesFromTable(
      table(["DRIVER", "GRID", "FINISH", "GAINED"], [
        ["NOR", "8", "3", "+5"],
        ["LEC", "6", "4", "+2"],
      ])
    );

    expect(series?.labelColumn).toBe("DRIVER");
    expect(series?.valueColumn).toBe("GAINED");
    expect(series?.points).toEqual([
      { label: "NOR", value: 5, display: "+5" },
      { label: "LEC", value: 2, display: "+2" },
    ]);
  });

  it("skips a non-numeric rightmost column and falls back to a numeric one", () => {
    const series = barSeriesFromTable(
      table(["DRIVER", "POINTS", "TEAM"], [
        ["NOR", "25", "McLaren"],
        ["LEC", "18", "Ferrari"],
      ])
    );
    expect(series?.valueColumn).toBe("POINTS");
  });

  it("keeps negative values", () => {
    const series = barSeriesFromTable(table(["D", "DELTA"], [["a", "-3"], ["b", "2"]]));
    expect(series?.points.map((p) => p.value)).toEqual([-3, 2]);
  });

  it.each([
    ["no table", null],
    ["one column", table(["D"], [["a"], ["b"]])],
    ["a single row", table(["D", "P"], [["a", "25"]])],
    ["more than 12 rows", table(["D", "P"], Array.from({ length: 13 }, (_, i) => [`d${i}`, `${i + 1}`]))],
    ["lap times", table(["D", "BEST"], [["a", "1:32.1"], ["b", "1:32.4"]])],
    ["an all-zero measure", table(["D", "X"], [["a", "0"], ["b", "0"]])],
    ["a missing cell", table(["D", "X"], [["a", "1"], ["b"]])],
  ])("returns null for %s", (_, input) => {
    expect(barSeriesFromTable(input)).toBeNull();
  });
});
