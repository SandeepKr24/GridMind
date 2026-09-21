// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LapPaceChart, PositionChangeChart, TyreStrategyChart } from "./RaceCharts";
import { ClassificationTable, PitStopTable, RaceControlList } from "./RaceTables";

afterEach(cleanup);

describe("PositionChangeChart", () => {
  it("shows gains with a plus sign and losses as negatives", () => {
    render(
      <PositionChangeChart
        changes={[
          { driver_name: "Lando Norris", driver_code: "NOR", grid_position: 8, finish_position: 3, positions_gained: 5 },
          { driver_name: "Max Verstappen", driver_code: "VER", grid_position: 1, finish_position: 4, positions_gained: -3 },
        ]}
      />
    );
    expect(screen.getByText("+5")).toBeTruthy();
    expect(screen.getByText("-3")).toBeTruthy();
  });

  it("has an empty state", () => {
    render(<PositionChangeChart changes={[]} />);
    expect(screen.getByText("No position data")).toBeTruthy();
  });
});

describe("LapPaceChart", () => {
  it("draws one line per driver with at least two laps", () => {
    render(
      <LapPaceChart
        traces={[
          { driver_code: "NOR", driver_name: "Lando Norris", laps: [
            { lap_number: 1, lap_time_ms: 92_000 },
            { lap_number: 2, lap_time_ms: 91_500 },
          ] },
          { driver_code: "LEC", driver_name: "Charles Leclerc", laps: [{ lap_number: 1, lap_time_ms: 92_300 }] },
        ]}
      />
    );
    expect(document.querySelectorAll("polyline")).toHaveLength(1);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Lando Norris");
  });

  it("has an empty state when no driver has enough laps", () => {
    render(<LapPaceChart traces={[]} />);
    expect(screen.getByText("No lap times")).toBeTruthy();
  });
});

describe("TyreStrategyChart", () => {
  it("shows stop counts and a legend of compounds used", () => {
    render(
      <TyreStrategyChart
        totalLaps={null}
        strategies={[
          { driver_name: "Lando Norris", driver_code: "NOR", stop_count: 1, stints: [
            { compound: "MEDIUM", start_lap: 1, end_lap: 20 },
            { compound: "HARD", start_lap: 21, end_lap: 53 },
          ] },
        ]}
      />
    );
    expect(screen.getByText("1-STOP")).toBeTruthy();
    expect(screen.getByText("MEDIUM")).toBeTruthy();
    expect(screen.getByText("HARD")).toBeTruthy();
    expect(screen.getByTitle("HARD · laps 21-53")).toBeTruthy();
  });

  it("has an empty state", () => {
    render(<TyreStrategyChart strategies={[]} totalLaps={53} />);
    expect(screen.getByText("No stint data")).toBeTruthy();
  });
});

describe("ClassificationTable", () => {
  it("shows every row, with dashes for missing values", () => {
    render(
      <ClassificationTable
        rows={[
          { position: 1, driver_name: "Lando Norris", driver_code: "NOR", constructor_name: "McLaren", grid_position: 2, points: 25, status: "Finished", best_lap_time: "1:21.0", pit_stop_count: 1, gap_to_leader: null },
          { position: 2, driver_name: "Charles Leclerc", driver_code: "LEC", constructor_name: "Ferrari", grid_position: null, points: 18, status: "Finished", best_lap_time: null, pit_stop_count: null, gap_to_leader: "+1.2" },
        ]}
      />
    );
    expect(screen.getByText("WINNER")).toBeTruthy();
    expect(screen.getByText("+1.2")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("has an empty state", () => {
    render(<ClassificationTable rows={[]} />);
    expect(screen.getByText("No classification")).toBeTruthy();
  });
});

describe("PitStopTable", () => {
  it("formats lap and duration", () => {
    render(<PitStopTable stops={[{ driver_name: "Lando Norris", driver_code: "NOR", lap: 18, duration_seconds: 2.4 }]} />);
    expect(screen.getByText("L18")).toBeTruthy();
    expect(screen.getByText("2.40s")).toBeTruthy();
  });

  it("has an empty state", () => {
    render(<PitStopTable stops={[]} />);
    expect(screen.getByText("No pit stops recorded")).toBeTruthy();
  });
});

describe("RaceControlList", () => {
  it("shows messages verbatim, with a dash when the lap is unknown", () => {
    render(
      <RaceControlList
        events={[
          { lap: 12, event_type: "SAFETY CAR", message: "SAFETY CAR DEPLOYED", timestamp: null },
          { lap: null, event_type: "FLAG", message: "GREEN LIGHT - PIT EXIT OPEN", timestamp: null },
        ]}
      />
    );
    expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeTruthy();
    expect(screen.getByText("L12")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("has an empty state", () => {
    render(<RaceControlList events={[]} />);
    expect(screen.getByText("No race control messages")).toBeTruthy();
  });
});
