import { describe, expect, it } from "vitest";
import { formatLapTime, lapTicks, orderByFinish, paceDomain, timeTicks } from "./charts";

describe("formatLapTime", () => {
  it("formats milliseconds as m:ss.s, or m:ss for whole seconds", () => {
    expect(formatLapTime(106_653)).toBe("1:46.653");
    expect(formatLapTime(106_000, { axis: true })).toBe("1:46");
    expect(formatLapTime(106_500, { axis: true })).toBe("1:46.5");
    expect(formatLapTime(59_900)).toBe("0:59.900");
  });
});

describe("paceDomain", () => {
  const racing = Array.from({ length: 40 }, (_, i) => 106_000 + (i % 10) * 200);

  it("keeps a real racing lap that is merely slow, like a heavy-fuel early lap", () => {
    // Lap 1 slower than every racing lap, but inside the fence; two pit laps far outside.
    const laps = [...racing, 108_600, 128_000, 131_000];
    const { max } = paceDomain(laps);
    expect(max).toBeGreaterThan(108_600);
  });

  it("fits the racing laps, so pit and safety-car laps don't flatten them", () => {
    const laps = [...racing, 128_000, 131_000, 150_000]; // two pit laps, a safety car lap
    const { min, max, clipped } = paceDomain(laps);

    expect(min).toBeLessThanOrEqual(106_000);
    expect(max).toBeLessThan(115_000);
    expect(clipped).toBe(true);
  });

  it("shows everything when nothing is an outlier", () => {
    const { max, clipped } = paceDomain(racing);
    expect(max).toBeGreaterThanOrEqual(107_800);
    expect(clipped).toBe(false);
  });

  it("never collapses to a zero-height range", () => {
    const { min, max } = paceDomain([100_000, 100_000]);
    expect(max).toBeGreaterThan(min);
  });
});

describe("timeTicks", () => {
  it("picks round steps that land inside the range", () => {
    expect(timeTicks(105_800, 109_300)).toEqual([106_000, 107_000, 108_000, 109_000]);
    expect(timeTicks(106_100, 107_300)).toEqual([106_500, 107_000]);
  });
});

describe("lapTicks", () => {
  it("labels round laps and always the last one", () => {
    expect(lapTicks(44)).toEqual([1, 10, 20, 30, 40, 44]);
    expect(lapTicks(12)).toEqual([1, 5, 10, 12]);
  });

  it("drops a round tick that would crowd the final lap", () => {
    expect(lapTicks(41)).toEqual([1, 10, 20, 30, 41]);
  });

  it("drops it sooner on a narrow chart, where labels need more laps of room", () => {
    expect(lapTicks(44, 6)).toEqual([1, 10, 20, 30, 44]);
  });
});

describe("orderByFinish", () => {
  it("sorts by finishing order and keeps unknown drivers at the end, in their order", () => {
    const items = [{ driver_code: "ZHO" }, { driver_code: "VER" }, { driver_code: "HAM" }, { driver_code: "XXX" }];
    expect(orderByFinish(items, ["HAM", "VER", "ZHO"]).map((i) => i.driver_code)).toEqual([
      "HAM",
      "VER",
      "ZHO",
      "XXX",
    ]);
  });

  it("returns the input order when no finishing order is known", () => {
    const items = [{ driver_code: "B" }, { driver_code: "A" }];
    expect(orderByFinish(items, []).map((i) => i.driver_code)).toEqual(["B", "A"]);
  });
});
