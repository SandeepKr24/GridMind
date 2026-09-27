// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

const lenis = vi.hoisted(() => ({
  options: [] as unknown[],
  scrollTo: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("lenis", () => ({
  default: vi.fn(function (this: unknown, options: unknown) {
    lenis.options.push(options);
    return { scrollTo: lenis.scrollTo, destroy: lenis.destroy };
  }),
}));

import { scrollToElement, startSmoothScroll } from "./smoothScroll";

// jsdom has none; the real browser check lives in startSmoothScroll.
vi.stubGlobal("ResizeObserver", class {});

function target() {
  const el = document.createElement("section");
  el.scrollIntoView = vi.fn();
  return el;
}

afterEach(() => {
  lenis.options.length = 0;
  lenis.scrollTo.mockClear();
  lenis.destroy.mockClear();
});

describe("smooth scrolling", () => {
  it("leaves boxes that scroll themselves to scroll natively", () => {
    const stop = startSmoothScroll();
    expect(lenis.options[0]).toMatchObject({ allowNestedScroll: true });
    stop();
  });

  it("glides through Lenis while it runs", () => {
    const stop = startSmoothScroll();
    const el = target();

    scrollToElement(el, false);

    expect(lenis.scrollTo).toHaveBeenCalledWith(el);
    expect(el.scrollIntoView).not.toHaveBeenCalled();
    stop();
  });

  it("jumps without Lenis under reduced motion", () => {
    const stop = startSmoothScroll();
    const el = target();

    scrollToElement(el, true);

    expect(lenis.scrollTo).not.toHaveBeenCalled();
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
    stop();
  });

  it("falls back to the browser once stopped", () => {
    startSmoothScroll()();
    const el = target();

    scrollToElement(el, false);

    expect(lenis.destroy).toHaveBeenCalledOnce();
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });
});
