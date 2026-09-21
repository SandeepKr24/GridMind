"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  | { status: "idle"; data: null; error: null }
  | { status: "loading"; data: null; error: null }
  | { status: "success"; data: T; error: null }
  | { status: "error"; data: null; error: unknown };

/**
 * Minimal data-fetching hook. Deliberately not a server-state library — the
 * frontend plan says not to add one until API caching actually gets complex.
 *
 * Every screen using this handles all four states, which is the point: with no
 * backend running, "error" is the honest thing to show rather than a placeholder.
 */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean } = {}
) {
  const enabled = options.enabled ?? true;
  const [reloadToken, setReloadToken] = useState(0);

  // A primitive identity for the current request. Changing it resets state.
  const requestKey = JSON.stringify([deps, enabled, reloadToken]);

  const [state, setState] = useState<AsyncState<T>>(() => ({
    status: enabled ? "loading" : "idle",
    data: null,
    error: null,
  }));

  // Reset during render when the request identity changes. This is React's
  // documented pattern for deriving state from changing inputs, and avoids the
  // cascading re-render that setState-inside-an-effect would cause.
  const [renderedKey, setRenderedKey] = useState(requestKey);
  if (renderedKey !== requestKey) {
    setRenderedKey(requestKey);
    setState({
      status: enabled ? "loading" : "idle",
      data: null,
      error: null,
    });
  }

  // Callers pass inline closures, so `fn` changes every render. Keep the latest
  // in a ref, updated in an effect rather than during render.
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });

  const reload = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    fnRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", data: null, error });
      });

    return () => {
      cancelled = true;
    };
  }, [requestKey, enabled]);

  return { ...state, reload };
}
