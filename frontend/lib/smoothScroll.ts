import Lenis from "lenis";

/**
 * Smoothed wheel and touchpad scrolling for the whole page, via Lenis.
 *
 * CSS `scroll-behavior: smooth` only animates jumps (anchors, scrollIntoView);
 * wheel steps stay abrupt. Lenis eases those too, while the page still scrolls
 * natively underneath, so sticky elements, scroll margins and keyboard
 * scrolling keep working.
 *
 * One instance at a time. The section nav asks for it through
 * `scrollToElement`, because with Lenis running, the browser's own smooth
 * scrolling is switched off and `scrollIntoView` would jump.
 */
let active: Lenis | null = null;

/** Starts smoothing. Returns the cleanup, for a React effect. */
export function startSmoothScroll(): () => void {
  // Lenis measures the page with ResizeObserver. Without it (jsdom, very old
  // browsers) the page simply keeps native scrolling.
  if (typeof ResizeObserver === "undefined") return () => {};
  const lenis = new Lenis({
    autoRaf: true,
    // Boxes that scroll themselves (race control, chat, wide tables) keep
    // their own native scrolling instead of moving the page.
    allowNestedScroll: true,
  });
  active = lenis;
  return () => {
    lenis.destroy();
    if (active === lenis) active = null;
  };
}

/** Scrolls to an element, honouring its CSS scroll-margin either way. */
export function scrollToElement(target: HTMLElement, reducedMotion: boolean): void {
  if (active && !reducedMotion) {
    active.scrollTo(target);
    return;
  }
  target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}
