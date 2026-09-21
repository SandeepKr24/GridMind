// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/chat",
  useSearchParams: () => new URLSearchParams(search),
}));

import { useAsync } from "./useAsync";
import {
  askHref,
  isValidJobId,
  isValidQuestion,
  MAX_QUESTION_LENGTH,
  useUrlParam,
} from "./useUrlParam";
import {
  availableSeasons,
  currentSeason,
  FIRST_SEASON,
  isValidSeason,
  useSeason,
} from "./useSeason";
import { useReducedMotion, useSound } from "./useSound";

beforeEach(() => {
  search = "";
  replace.mockClear();
  window.localStorage.clear();
});

describe("useUrlParam", () => {
  it("reads a valid value", () => {
    search = "job=job_1";
    const { result } = renderHook(() => useUrlParam("job", isValidJobId));
    expect(result.current[0]).toBe("job_1");
  });

  it("reads an invalid value as null", () => {
    search = "job=javascript:alert(1)";
    const { result } = renderHook(() => useUrlParam("job", isValidJobId));
    expect(result.current[0]).toBeNull();
  });

  it("sets a value while keeping the other params", () => {
    search = "q=hello";
    const { result } = renderHook(() => useUrlParam("job", isValidJobId));

    act(() => result.current[1]("job_2"));

    expect(replace).toHaveBeenCalledWith("/chat?q=hello&job=job_2", { scroll: false });
  });

  it("removes a value, leaving a clean path", () => {
    search = "job=job_1";
    const { result } = renderHook(() => useUrlParam("job", isValidJobId));

    act(() => result.current[1](null));

    expect(replace).toHaveBeenCalledWith("/chat", { scroll: false });
  });
});

describe("URL value checks", () => {
  it.each([
    ["job_8f3a-12", true],
    ["a".repeat(64), true],
    ["a".repeat(65), false],
    ["", false],
    ["../etc", false],
    ["job 1", false],
  ])("isValidJobId(%j) is %s", (value, expected) => {
    expect(isValidJobId(value)).toBe(expected);
  });

  it("isValidQuestion rejects blank and over-long questions", () => {
    expect(isValidQuestion("Who won?")).toBe(true);
    expect(isValidQuestion("   ")).toBe(false);
    expect(isValidQuestion("x".repeat(MAX_QUESTION_LENGTH + 1))).toBe(false);
  });

  it("askHref encodes the question", () => {
    expect(askHref("Who won at São Paulo?")).toBe(
      "/chat?q=Who%20won%20at%20S%C3%A3o%20Paulo%3F"
    );
  });
});

describe("seasons", () => {
  it("lists seasons newest first, from now back to the first with timing data", () => {
    const seasons = availableSeasons();
    expect(seasons[0]).toBe(currentSeason());
    expect(seasons.at(-1)).toBe(FIRST_SEASON);
  });

  it.each([
    [FIRST_SEASON, true],
    [FIRST_SEASON - 1, false],
    [currentSeason() + 1, false],
    [2020.5, false],
    [Number.NaN, false],
  ])("isValidSeason(%s) is %s", (value, expected) => {
    expect(isValidSeason(value)).toBe(expected);
  });

  it("defaults to the current season and remembers a choice", () => {
    const { result } = renderHook(() => useSeason());
    expect(result.current[0]).toBe(currentSeason());

    act(() => result.current[1](2021));

    expect(result.current[0]).toBe(2021);
    expect(window.localStorage.getItem("gm.season")).toBe("2021");
  });

  it("ignores a tampered stored value and an invalid choice", () => {
    window.localStorage.setItem("gm.season", "1066");
    const { result } = renderHook(() => useSeason());
    expect(result.current[0]).toBe(currentSeason());

    act(() => result.current[1](1999));
    expect(result.current[0]).toBe(currentSeason());
  });
});

describe("useAsync", () => {
  it("goes loading then success", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve(42), []));

    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toBe(42);
  });

  it("reports an error", async () => {
    const failure = new Error("nope");
    const { result } = renderHook(() => useAsync(() => Promise.reject(failure), []));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe(failure);
  });

  it("stays idle when disabled", () => {
    const fn = vi.fn(() => Promise.resolve(1));
    const { result } = renderHook(() => useAsync(fn, [], { enabled: false }));

    expect(result.current.status).toBe("idle");
    expect(fn).not.toHaveBeenCalled();
  });

  it("refetches on reload and when deps change", async () => {
    let n = 0;
    const { result, rerender } = renderHook(({ dep }) => useAsync(() => Promise.resolve(++n), [dep]), {
      initialProps: { dep: "a" },
    });
    await waitFor(() => expect(result.current.data).toBe(1));

    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe(2));

    rerender({ dep: "b" });
    await waitFor(() => expect(result.current.data).toBe(3));
  });

  it("ignores a stale response after deps change", async () => {
    let resolveFirst: (v: string) => void = () => {};
    const first = new Promise<string>((r) => (resolveFirst = r));
    const { result, rerender } = renderHook(
      ({ dep }) => useAsync(() => (dep === "a" ? first : Promise.resolve("second")), [dep]),
      { initialProps: { dep: "a" } }
    );

    rerender({ dep: "b" });
    await waitFor(() => expect(result.current.data).toBe("second"));

    await act(async () => resolveFirst("first"));
    expect(result.current.data).toBe("second");
  });
});

describe("useSound", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is muted by default and remembers the toggle", () => {
    const { result } = renderHook(() => useSound());
    expect(result.current.enabled).toBe(false);

    act(() => result.current.toggle());

    expect(result.current.enabled).toBe(true);
    expect(window.localStorage.getItem("gm.sound")).toBe("1");
  });

  it("plays nothing while muted", () => {
    const ctor = vi.fn();
    vi.stubGlobal("AudioContext", ctor);
    const { result } = renderHook(() => useSound());

    act(() => result.current.beepForStage(0, false));

    expect(ctor).not.toHaveBeenCalled();
  });

  it("plays a tone when enabled", () => {
    const start = vi.fn();
    const node = () => ({
      connect: vi.fn(),
      start,
      stop: vi.fn(),
      frequency: { value: 0 },
      gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
    });
    class FakeAudioContext {
      state = "running";
      currentTime = 0;
      destination = {};
      createOscillator = node;
      createGain = node;
      resume = vi.fn();
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    window.localStorage.setItem("gm.sound", "1");

    const { result } = renderHook(() => useSound());
    act(() => result.current.beepForStage(4, true));

    expect(start).toHaveBeenCalledTimes(1);
  });
});

describe("useReducedMotion", () => {
  it("reflects the media query", () => {
    const listeners: ((e: { matches: boolean }) => void)[] = [];
    let matches = true;
    vi.stubGlobal("matchMedia", () => ({
      get matches() {
        return matches;
      },
      addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => listeners.push(cb),
      removeEventListener: vi.fn(),
    }));

    const { result } = renderHook(() => useReducedMotion());
    expect(result.current).toBe(true);

    act(() => {
      matches = false;
      listeners.forEach((cb) => cb({ matches: false }));
    });
    expect(result.current).toBe(false);
  });
});
