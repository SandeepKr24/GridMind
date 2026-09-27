import { describe, expect, it } from "vitest";
import type { GridDriver } from "@/lib/api/types";
import { DRIVER_BIOS, TEAM_INFO, driverName, groupTeams } from "./grid";

function driver(number: number, code: string, team: string): GridDriver {
  return {
    number,
    code,
    first_name: "First",
    last_name: code,
    team_name: team,
    team_colour: null,
    headshot_url: null,
  };
}

describe("groupTeams", () => {
  it("groups drivers by team, teams ordered by their lowest car number", () => {
    const teams = groupTeams([
      driver(81, "PIA", "McLaren"),
      driver(44, "HAM", "Ferrari"),
      driver(1, "NOR", "McLaren"),
      driver(16, "LEC", "Ferrari"),
    ]);

    expect(teams.map((t) => [t.name, t.key, t.drivers.map((d) => d.code)])).toEqual([
      ["McLaren", "mclaren", ["NOR", "PIA"]],
      ["Ferrari", "ferrari", ["LEC", "HAM"]],
    ]);
  });

  it("leaves the input untouched", () => {
    const input = [driver(81, "PIA", "McLaren"), driver(1, "NOR", "McLaren")];
    groupTeams(input);
    expect(input.map((d) => d.code)).toEqual(["PIA", "NOR"]);
  });
});

describe("grid text", () => {
  it("has a full name and bio for every team on the 2026 grid", () => {
    const keys = [
      "mercedes", "ferrari", "mclaren", "red_bull", "rb", "alpine",
      "haas", "audi", "williams", "aston_martin", "cadillac",
    ] as const;
    for (const key of keys) {
      expect(TEAM_INFO[key]?.fullName, key).toBeTruthy();
      expect(TEAM_INFO[key]?.bio, key).toBeTruthy();
    }
  });

  it("keeps bios short and free of dashes", () => {
    for (const [code, bio] of Object.entries(DRIVER_BIOS)) {
      expect(bio.length, code).toBeLessThan(260);
      expect(bio, code).not.toMatch(/[—–]/);
    }
  });

  it("joins first and last names", () => {
    expect(driverName(driver(1, "NOR", "McLaren"))).toBe("First NOR");
  });
});
