// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// lib/teams reads the logo list when it loads, so set it before any import.
vi.hoisted(() => {
  process.env.NEXT_PUBLIC_TEAM_LOGOS = "mclaren.png,red_bull.png";
});

vi.mock("@/lib/api/grid", () => ({ getGrid: vi.fn() }));

import { getGrid } from "@/lib/api/grid";
import { ApiError } from "@/lib/api/client";
import type { CurrentGrid, GridDriver } from "@/lib/api/types";
import DriversPage from "./drivers/page";
import TeamsPage from "./teams/page";

const api = { getGrid: vi.mocked(getGrid) };

const HEADSHOT =
  "https://media.formula1.com/d_driver_fallback_image.png/content/dam/fom-website/drivers/L/LANNOR01_Lando_Norris/lannor01.png.transform/2col/image.png";

function driver(extra: Partial<GridDriver>): GridDriver {
  return {
    number: 1,
    code: "NOR",
    first_name: "Lando",
    last_name: "Norris",
    team_name: "McLaren",
    team_colour: "#F47600",
    headshot_url: HEADSHOT,
    ...extra,
  };
}

const grid: CurrentGrid = {
  season: 2026,
  race_location: "Baku",
  race_date: "2026-09-26",
  fetched_at: "2026-09-27T10:00:00+00:00",
  is_stale: false,
  drivers: [
    driver({}),
    driver({ number: 81, code: "PIA", first_name: "Oscar", last_name: "Piastri" }),
    driver({
      number: 3,
      code: "VER",
      first_name: "Max",
      last_name: "Verstappen",
      team_name: "Red Bull Racing",
      team_colour: "#4781D7",
    }),
    // No bio, no photo: a newcomer the static text does not know yet.
    driver({
      number: 99,
      code: "NEW",
      first_name: "Rookie",
      last_name: "Driver",
      team_name: "Cadillac",
      team_colour: null,
      headshot_url: null,
    }),
  ],
};

// No per-test reset: every test sets its own result, and in this Vitest a
// cleared or reset mock reports a rejected promise as unhandled even though
// the page catches it and shows the error state.
afterEach(cleanup);

describe("Drivers page", () => {
  it("lists every driver with name, number, team, bio and headshot", async () => {
    api.getGrid.mockResolvedValue(grid);
    render(<DriversPage />);

    expect(await screen.findByRole("heading", { name: "2026 Drivers" })).toBeTruthy();
    expect(screen.getByText("As raced at Baku on 2026-09-26.")).toBeTruthy();
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(4);

    const norris = within(cards[0]!);
    expect(norris.getByRole("heading", { name: "Lando Norris" })).toBeTruthy();
    expect(norris.getByText("#1 · NOR")).toBeTruthy();
    expect(norris.getByText(/World Championship in 2025/)).toBeTruthy();
    const photo = norris.getByRole("img", { name: "Lando Norris, official headshot" });
    expect(photo.getAttribute("src")).toBe(HEADSHOT);
  });

  it("keeps teammates side by side, teams ordered by their lowest number", async () => {
    api.getGrid.mockResolvedValue(grid);
    render(<DriversPage />);

    const names = (await screen.findAllByRole("article")).map(
      (card) => within(card).getByRole("heading").textContent
    );
    expect(names).toEqual(["Lando Norris", "Oscar Piastri", "Max Verstappen", "Rookie Driver"]);
  });

  it("shows the driver's code when the headshot is missing or fails to load", async () => {
    api.getGrid.mockResolvedValue(grid);
    render(<DriversPage />);
    const cards = await screen.findAllByRole("article");

    expect(within(cards[3]!).getByText("NEW")).toBeTruthy();

    fireEvent.error(within(cards[0]!).getByRole("img", { name: /official headshot/ }));
    expect(within(cards[0]!).queryByRole("img", { name: /official headshot/ })).toBeNull();
    expect(within(cards[0]!).getByText("NOR")).toBeTruthy();
  });

  it("says when the line-up is an older copy", async () => {
    api.getGrid.mockResolvedValue({ ...grid, is_stale: true });
    render(<DriversPage />);
    expect(await screen.findByText(/source is unreachable/)).toBeTruthy();
  });

  it("explains when the grid cannot be loaded", async () => {
    api.getGrid.mockImplementation(() => Promise.reject(new ApiError("network", "down")));
    render(<DriversPage />);
    expect(await screen.findByText("NO CONNECTION TO THE BACKEND")).toBeTruthy();
  });
});

describe("Teams page", () => {
  it("lists each team once with its full name, bio, logo and drivers", async () => {
    api.getGrid.mockResolvedValue(grid);
    render(<TeamsPage />);

    expect(await screen.findByRole("heading", { name: "2026 Teams" })).toBeTruthy();
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(3);

    const mclaren = within(cards[0]!);
    expect(mclaren.getByRole("heading", { name: "McLaren Mastercard F1 Team" })).toBeTruthy();
    expect(mclaren.getByText(/Woking/)).toBeTruthy();
    expect(mclaren.getByText("Lando Norris #1 · Oscar Piastri #81")).toBeTruthy();
    expect(mclaren.getByRole("img", { name: "McLaren logo" }).getAttribute("src")).toBe(
      "/teams/mclaren.png"
    );
    expect(within(cards[1]!).getByRole("heading", { name: "Oracle Red Bull Racing" })).toBeTruthy();
  });
});
