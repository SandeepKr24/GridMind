import { useEffect, type RefObject } from "react";

/**
 * Keeps a CSS variable on <html> equal to an element's height, so styles
 * elsewhere can account for it. Used for the sticky header and the race page's
 * floating section nav: in-page jumps must land below both (globals.css), and
 * both change height when they wrap on narrow screens.
 *
 * The variable is removed on unmount, so a page that no longer shows the
 * element stops reserving space for it.
 */
export function usePublishedHeight(ref: RefObject<HTMLElement | null>, cssVariable: string) {
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const root = document.documentElement;
    const update = () => root.style.setProperty(cssVariable, `${element.offsetHeight}px`);
    update();

    // Missing in old browsers and in jsdom: the one measurement above stands.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      root.style.removeProperty(cssVariable);
    };
  }, [ref, cssVariable]);
}
