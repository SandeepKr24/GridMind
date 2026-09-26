import { describe, expect, it } from "vitest";
import { formatTimestamp } from "./format";

describe("formatTimestamp", () => {
  it("formats a backend timestamp as a readable UTC date and time", () => {
    expect(formatTimestamp("2026-09-26T14:51:02.629664+00:00")).toBe("26 Sep 2026, 14:51 UTC");
  });

  it("converts other offsets to UTC", () => {
    expect(formatTimestamp("2025-09-07T18:00:00+02:00")).toBe("7 Sep 2025, 16:00 UTC");
  });

  it("returns an unparseable value unchanged rather than 'Invalid Date'", () => {
    expect(formatTimestamp("not a date")).toBe("not a date");
  });
});
