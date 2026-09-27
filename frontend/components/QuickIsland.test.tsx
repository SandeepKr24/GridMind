// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", async () => {
  const { createElement } = await import("react");
  return {
    default: ({ href, children, ...rest }: { href: string; children: ReactNode }) =>
      createElement("a", { href, ...rest }, children),
  };
});

import { QuickIsland } from "./QuickIsland";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const toggle = () => screen.getByRole("button", { name: "Quick links" });
const link = (name: RegExp) => screen.getByRole("link", { name, hidden: true });
const isOpen = () => toggle().getAttribute("aria-expanded") === "true";

describe("QuickIsland", () => {
  it("rests as the logo alone, its links out of reach", () => {
    render(<QuickIsland />);

    expect(isOpen()).toBe(false);
    expect(link(/Drivers/).getAttribute("tabindex")).toBe("-1");
    expect(link(/Drivers/).parentElement?.className).toContain("invisible");
  });

  it("opens under a mouse and closes shortly after the mouse leaves", () => {
    vi.useFakeTimers();
    render(<QuickIsland />);
    const island = toggle().parentElement!;

    fireEvent.pointerEnter(island, { pointerType: "mouse" });
    expect(isOpen()).toBe(true);
    expect(link(/Drivers/).getAttribute("tabindex")).toBeNull();

    fireEvent.pointerLeave(island, { pointerType: "mouse" });
    expect(isOpen()).toBe(true); // grace period, so the pointer can reach a link
    act(() => vi.advanceTimersByTime(300));
    expect(isOpen()).toBe(false);
  });

  it("links to the drivers page, the teams page and Forza Helper", () => {
    render(<QuickIsland />);

    expect(link(/^Drivers$/).getAttribute("href")).toBe("/drivers");
    expect(link(/^Teams$/).getAttribute("href")).toBe("/teams");
    const forza = link(/Forza Helper/);
    expect(forza.getAttribute("href")).toBe("https://forzahelper-fh6.vercel.app/");
    expect(forza.getAttribute("target")).toBe("_blank");
    expect(forza.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("stays open through a tap, which focuses and then clicks the logo", () => {
    render(<QuickIsland />);

    fireEvent.focus(toggle());
    fireEvent.click(toggle());

    expect(isOpen()).toBe(true);
  });

  it("toggles closed on a later click", () => {
    const now = vi.spyOn(performance, "now");
    render(<QuickIsland />);

    now.mockReturnValue(1000);
    fireEvent.click(toggle());
    now.mockReturnValue(3000);
    fireEvent.click(toggle());

    expect(isOpen()).toBe(false);
    now.mockRestore();
  });

  it("closes on Escape and hands focus back to the logo", () => {
    render(<QuickIsland />);
    fireEvent.click(toggle());

    fireEvent.keyDown(document, { key: "Escape" });

    expect(isOpen()).toBe(false);
    expect(document.activeElement).toBe(toggle());
  });

  it("closes when following a link", () => {
    render(<QuickIsland />);
    fireEvent.click(toggle());

    fireEvent.click(link(/^Teams$/));

    expect(isOpen()).toBe(false);
  });
});
