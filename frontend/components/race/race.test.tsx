// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LapPaceChart, PositionChangeChart, TyreStrategyChart } from "./RaceCharts";
import {
  ClassificationTable,
  parseLapFilter,
  PitStopTable,
  RaceControlList,
} from "./RaceTables";

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

  it("shows grid and finish for the driver under the pointer", () => {
    render(
      <PositionChangeChart
        changes={[
          { driver_name: "Lando Norris", driver_code: "NOR", grid_position: 8, finish_position: 3, positions_gained: 5 },
        ]}
      />
    );
    fireEvent.pointerEnter(screen.getByText("NOR").parentElement!);

    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("Lando Norris");
    expect(tip.textContent).toContain("P8grid");
    expect(tip.textContent).toContain("P3finish");
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
    expect(document.querySelectorAll("path[data-series]")).toHaveLength(1);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Lando Norris");
  });

  const lap = (lap_number: number, lap_time_ms: number) => ({ lap_number, lap_time_ms });
  const racing = Array.from({ length: 20 }, (_, i) => lap(i + 1, 106_000 + (i % 5) * 150));

  it("gives the winner the first colour, whatever order the traces arrive in", () => {
    render(
      <LapPaceChart
        finishOrder={["VER", "NOR"]}
        traces={[
          { driver_code: "NOR", driver_name: "Lando Norris", laps: racing },
          { driver_code: "VER", driver_name: "Max Verstappen", laps: racing },
        ]}
      />
    );
    const [first, second] = document.querySelectorAll("path[data-series]");
    expect(first!.getAttribute("data-series")).toBe("VER");
    expect(first!.getAttribute("stroke")).toBe("#3987e5");
    expect(second!.getAttribute("data-series")).toBe("NOR");
  });

  it("says when slow laps run off the top of the chart", () => {
    render(
      <LapPaceChart
        traces={[{ driver_code: "NOR", driver_name: "Lando Norris", laps: [...racing, lap(21, 130_000)] }]}
      />
    );
    expect(screen.getByText(/run off the top/)).toBeTruthy();
  });

  it("reads out every driver's time at a lap from the keyboard", () => {
    render(
      <LapPaceChart
        traces={[
          { driver_code: "NOR", driver_name: "Lando Norris", laps: [lap(1, 92_000), lap(2, 91_500)] },
          { driver_code: "LEC", driver_name: "Charles Leclerc", laps: [lap(1, 92_300), lap(2, 91_400)] },
        ]}
      />
    );
    const chart = screen.getByRole("img");
    fireEvent.focus(chart); // starts on the last lap

    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("Lap 2");
    expect(tip.textContent).toContain("1:31.400LEC"); // fastest first
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(screen.getByRole("tooltip").textContent).toContain("Lap 1");
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
    expect(screen.getByText("1 stop")).toBeTruthy();
    expect(screen.getByText("Medium")).toBeTruthy();
    expect(screen.getByText("Hard")).toBeTruthy();
    expect(screen.getByLabelText("HARD, laps 21-53")).toBeTruthy();
  });

  it("lists drivers in finishing order", () => {
    const stint = [{ compound: "SOFT" as const, start_lap: 1, end_lap: 10 }];
    render(
      <TyreStrategyChart
        totalLaps={10}
        finishOrder={["PIA", "NOR"]}
        strategies={[
          { driver_name: "Lando Norris", driver_code: "NOR", stop_count: 0, stints: stint },
          { driver_name: "Oscar Piastri", driver_code: "PIA", stop_count: 0, stints: stint },
        ]}
      />
    );
    const codes = screen.getAllByText(/^(NOR|PIA)$/).map((el) => el.textContent);
    expect(codes).toEqual(["PIA", "NOR"]);
  });

  it("shows a stint's laps under the pointer", () => {
    render(
      <TyreStrategyChart
        totalLaps={53}
        strategies={[
          { driver_name: "Lando Norris", driver_code: "NOR", stop_count: 1, stints: [
            { compound: "MEDIUM", start_lap: 1, end_lap: 20 },
            { compound: "HARD", start_lap: 21, end_lap: 53 },
          ] },
        ]}
      />
    );
    fireEvent.pointerEnter(screen.getByLabelText("HARD, laps 21-53"));

    const tip = screen.getByRole("tooltip");
    expect(tip.textContent).toContain("HARDlaps 21-53");
    expect(tip.textContent).toContain("33laps on this set");
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
    expect(screen.getAllByText("-").length).toBeGreaterThanOrEqual(3);
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

  it("scrolls inside the height the page gives it, with the headings pinned", () => {
    render(
      <PitStopTable
        stops={[{ driver_name: "Lando Norris", driver_code: "NOR", lap: 18, duration_seconds: 2.4 }]}
        className="md:absolute md:inset-0"
      />
    );
    const box = screen.getByRole("region", { name: "Pit stops" });
    expect(box.className).toContain("overflow-auto");
    expect(box.className).toContain("md:absolute");
    expect(box.getAttribute("tabindex")).toBe("0");
    expect(box.hasAttribute("data-lenis-prevent")).toBe(true);
    expect(screen.getByRole("columnheader", { name: "DRIVER" }).className).toContain("sticky");
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
    expect(screen.getByText("-")).toBeTruthy();
  });

  it("scrolls inside its panel instead of stretching the page", () => {
    render(
      <RaceControlList
        events={[{ lap: 1, event_type: "FLAG", message: "GREEN FLAG", timestamp: null }]}
      />
    );
    const box = screen.getByRole("region", { name: "Race control messages" });
    expect(box.className).toContain("overflow-y-auto");
    expect(box.className).toContain("max-h-");
    // Keyboard users can focus it and scroll with the arrow keys.
    expect(box.getAttribute("tabindex")).toBe("0");
    // Smooth page scrolling leaves it alone.
    expect(box.hasAttribute("data-lenis-prevent")).toBe(true);
  });

  it("has an empty state", () => {
    render(<RaceControlList events={[]} />);
    expect(screen.getByText("No race control messages")).toBeTruthy();
  });

  describe("lap filter", () => {
    const events = [
      { lap: null, event_type: "FLAG", message: "GREEN LIGHT - PIT EXIT OPEN", timestamp: null },
      { lap: 12, event_type: "SAFETY CAR", message: "SAFETY CAR DEPLOYED", timestamp: null },
      { lap: 12, event_type: "OTHER", message: "CAR 4 TIME DELETED", timestamp: null },
      { lap: 43, event_type: "FLAG", message: "CHEQUERED FLAG", timestamp: null },
    ];
    const lapBox = () => screen.getByLabelText("Lap");
    const listed = () =>
      within(screen.getByRole("region", { name: "Race control messages" }))
        .queryAllByRole("listitem")
        .map((item) => item.querySelector("p")?.textContent);

    it("shows every message while the box is empty", () => {
      render(<RaceControlList events={events} />);
      expect(listed()).toHaveLength(4);
      expect(screen.getByText("4 messages")).toBeTruthy();
    });

    it("shows only the messages of the lap typed in", () => {
      render(<RaceControlList events={events} />);

      fireEvent.change(lapBox(), { target: { value: "12" } });

      expect(listed()).toEqual(["SAFETY CAR DEPLOYED", "CAR 4 TIME DELETED"]);
      expect(screen.getByText("2 messages on lap 12")).toBeTruthy();
    });

    it("says so when a lap had no messages", () => {
      render(<RaceControlList events={events} />);

      fireEvent.change(lapBox(), { target: { value: "20" } });

      expect(listed()).toEqual([]);
      expect(screen.getByText("No race control messages on lap 20.")).toBeTruthy();
    });

    it("asks for a real lap when the number is out of range", () => {
      render(<RaceControlList events={events} />);

      fireEvent.change(lapBox(), { target: { value: "99" } });

      expect(listed()).toEqual([]);
      expect(screen.getByText("Enter a lap from 1 to 43")).toBeTruthy();
    });

    it("goes back to every message from Show all", () => {
      render(<RaceControlList events={events} />);
      fireEvent.change(lapBox(), { target: { value: "43" } });

      fireEvent.click(screen.getByRole("button", { name: "Show all" }));

      expect(listed()).toHaveLength(4);
      expect((lapBox() as HTMLInputElement).value).toBe("");
    });
  });
});

describe("parseLapFilter", () => {
  it.each([
    ["", { kind: "all" }],
    ["  ", { kind: "all" }],
    ["7", { kind: "lap", lap: 7 }],
    ["44", { kind: "lap", lap: 44 }],
    ["0", { kind: "invalid" }],
    ["45", { kind: "invalid" }],
    ["2.5", { kind: "invalid" }],
    ["-3", { kind: "invalid" }],
  ])("reads %j with 44 laps as %j", (text, expected) => {
    expect(parseLapFilter(text, 44)).toEqual(expected);
  });
});
