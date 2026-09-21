"use client";

import type { ReactNode } from "react";
import { describeError, ApiError } from "@/lib/api/client";
import { ErrorState, SkeletonRows } from "@/components/ui/primitives";
import type { AsyncState } from "@/lib/hooks/useAsync";

/**
 * Renders the four states of a request so no screen can accidentally show
 * nothing, or worse, show a plausible-looking placeholder that is not real data.
 */
export function AsyncBoundary<T>({
  state,
  onRetry,
  loading,
  children,
}: {
  state: AsyncState<T> & { reload?: () => void };
  onRetry?: () => void;
  loading?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (state.status === "loading" || state.status === "idle") {
    return <>{loading ?? <SkeletonRows />}</>;
  }

  if (state.status === "error") {
    const { title, body } = describeError(state.error);
    const retry =
      onRetry ??
      (state.reload as (() => void) | undefined) ??
      undefined;

    // A 404 is not a crash — the caller usually wants an empty state instead.
    return <ErrorState title={title} body={body} onRetry={retry} />;
  }

  return <>{children(state.data)}</>;
}

/** True when the failure means "this thing does not exist" rather than "it broke". */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.kind === "not_found";
}
