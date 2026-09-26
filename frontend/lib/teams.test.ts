import { describe, expect, it } from "vitest";
import { parseLogoList, teamColor, teamKey, teamLogoSrc } from "./teams";

describe("teamKey", () => {
  it.each([
    ["Red Bull Racing", "red_bull"],
    ["McLaren", "mclaren"],
    ["Haas F1 Team", "haas"],
    ["Kick Sauber", "sauber"],
    ["Racing Bulls", "rb"],
    ["RB", "rb"],
    ["Visa Cash App RB", "rb"],
    ["Aston Martin Aramco", "aston_martin"],
  ])("maps %s to %s", (name, key) => {
    expect(teamKey(name)).toBe(key);
  });

  it("keeps renamed teams' earlier identities apart, since their logos differ", () => {
    expect(teamKey("Toro Rosso")).toBe("toro_rosso");
    expect(teamKey("AlphaTauri")).toBe("alphatauri");
    expect(teamKey("Alfa Romeo")).toBe("alfa_romeo");
    expect(teamKey("Racing Point")).toBe("racing_point");
  });

  it("ignores case, spacing and punctuation", () => {
    expect(teamKey("  red bull  RACING ")).toBe("red_bull");
    expect(teamKey("Haas-F1-Team")).toBe("haas");
  });

  it("returns null for anything that is not a known team", () => {
    expect(teamKey("Lewis Hamilton")).toBeNull();
    expect(teamKey("")).toBeNull();
    expect(teamKey("—")).toBeNull();
  });
});

describe("teamColor", () => {
  it("gives a known team its livery colour and anything else a neutral one", () => {
    expect(teamColor("mclaren")).toBe("#FF8000");
    expect(teamColor(null)).toBe("#3A4049");
  });
});

describe("logos", () => {
  const available = parseLogoList("mclaren.svg,ferrari.png,notes.txt,ferrari.svg,.gitkeep");

  it("finds a team's logo file, preferring SVG over PNG", () => {
    expect(teamLogoSrc("mclaren", available)).toBe("/teams/mclaren.svg");
    expect(teamLogoSrc("ferrari", available)).toBe("/teams/ferrari.svg");
  });

  it("has no logo for a team without a file, so the colour mark is used", () => {
    expect(teamLogoSrc("williams", available)).toBeNull();
    expect(teamLogoSrc(null, available)).toBeNull();
  });

  it("ignores files that are not images, and an empty list", () => {
    expect(teamLogoSrc("notes" as never, available)).toBeNull();
    expect(parseLogoList(undefined).size).toBe(0);
    expect(parseLogoList("").size).toBe(0);
  });
});
