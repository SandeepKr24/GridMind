import { describe, expect, it } from "vitest";
import { stripDashes, stripDashesDeep } from "./text";

describe("stripDashes", () => {
  it("turns a spaced dash into a comma", () => {
    expect(stripDashes("Verstappen won — by 3s")).toBe("Verstappen won, by 3s");
  });

  it("turns ranges and lone dashes into hyphens", () => {
    expect(stripDashes("laps 21–53")).toBe("laps 21-53");
    expect(stripDashes("—")).toBe("-");
  });

  it("cleans every string in a nested value and leaves the rest alone", () => {
    const input = { text: "a – b", rows: [["—", 3]], n: null };
    expect(stripDashesDeep(input)).toEqual({ text: "a, b", rows: [["-", 3]], n: null });
  });
});
