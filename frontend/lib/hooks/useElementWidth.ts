import { useEffect, useRef, useState } from "react";

/**
 * An element's rendered width, kept current. Charts draw at real pixel width
 * so axis text stays 12px on a phone instead of shrinking with a scaled
 * viewBox. Until the first measurement (and where ResizeObserver is missing,
 * as in jsdom) it reports `fallback`.
 */
export function useElementWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      if (element.clientWidth > 0) setWidth(element.clientWidth);
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}
