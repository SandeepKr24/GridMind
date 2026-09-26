// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.resetModules();
});

/** The logo list is read when lib/teams loads, so each case imports afresh. */
async function renderTeam(name: string, logos = "") {
  vi.stubEnv("NEXT_PUBLIC_TEAM_LOGOS", logos);
  const { TeamName } = await import("./TeamName");
  return render(<TeamName name={name} />);
}

describe("TeamName", () => {
  it("shows the team's logo when a file exists for it", async () => {
    await renderTeam("McLaren", "mclaren.svg");

    const logo = screen.getByTestId("team-logo");
    expect(logo.getAttribute("src")).toBe("/teams/mclaren.svg");
    expect(logo.getAttribute("alt")).toBe(""); // the name beside it is read out
    expect(screen.getByText("McLaren")).toBeTruthy();
  });

  it("falls back to a bar in the livery colour when there is no logo", async () => {
    await renderTeam("McLaren", "ferrari.svg");

    expect(screen.queryByTestId("team-logo")).toBeNull();
    const mark = screen.getByTestId("team-colour");
    expect(mark.style.backgroundColor).toBe("rgb(255, 128, 0)");
    expect(mark.getAttribute("aria-hidden")).toBe("true");
  });

  it("gives an unknown team a neutral mark and still shows its name", async () => {
    await renderTeam("Brawn GP");

    expect(screen.getByTestId("team-colour").style.backgroundColor).toBe("rgb(58, 64, 73)");
    expect(screen.getByText("Brawn GP")).toBeTruthy();
  });
});
