/**
 * Typed fetch wrapper for the GridMind backend.
 *
 * Two rules carried over from the frontend plan:
 *
 * 1. No blanket short timeout. A cold question legitimately takes 30-120s, so a
 *    30s default would make every cold request look like a failure. Callers pass
 *    a timeout appropriate to the endpoint; job polls get a generous one.
 * 2. Failures are classified, not collapsed. "Rate limited" and "backend
 *    unreachable" need different copy, so they get different error kinds.
 */

import { stripDashesDeep } from "@/lib/text";

export type ApiErrorKind =
  | "network" // backend unreachable — almost always "not running yet" in dev
  | "timeout"
  | "rate_limited" // 429
  | "not_found" // 404
  | "conflict" // 409 — e.g. job already running
  | "server" // 5xx
  | "client" // other 4xx
  | "malformed"; // 2xx but the body was not what we expected

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** Seconds to wait before retrying, from the Retry-After header when present. */
  readonly retryAfterSeconds: number | null;

  constructor(
    kind: ApiErrorKind,
    message: string,
    status: number | null = null,
    retryAfterSeconds: number | null = null
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** True when retrying the same request might succeed without user changes. */
  get isTransient(): boolean {
    return (
      this.kind === "network" ||
      this.kind === "timeout" ||
      this.kind === "rate_limited" ||
      this.kind === "server"
    );
  }
}

const DEFAULT_TIMEOUT_MS = 20_000;

export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  return raw.replace(/\/+$/, "");
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) ? seconds : null;
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown; message?: unknown };
    const candidate = body.detail ?? body.message;
    if (typeof candidate === "string" && candidate.trim().length > 0) {
      detail = candidate;
    }
  } catch {
    // Body was not JSON. The status line is all we have, which is fine.
  }

  const retryAfter = parseRetryAfter(res.headers.get("Retry-After"));

  if (res.status === 429) {
    return new ApiError("rate_limited", detail, res.status, retryAfter);
  }
  if (res.status === 404) return new ApiError("not_found", detail, res.status);
  if (res.status === 409) return new ApiError("conflict", detail, res.status);
  if (res.status >= 500) return new ApiError("server", detail, res.status);
  return new ApiError("client", detail, res.status);
}

export async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const base = apiBaseUrl();
  if (!base) {
    throw new ApiError(
      "network",
      "No backend URL configured. Set NEXT_PUBLIC_API_BASE_URL."
    );
  }

  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // Let a caller-supplied signal also abort this request.
  const onExternalAbort = () => controller.abort();
  signal?.addEventListener("abort", onExternalAbort);

  try {
    const res = await fetch(`${base}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });

    if (!res.ok) throw await errorFromResponse(res);

    if (res.status === 204) return undefined as T;

    try {
      return stripDashesDeep((await res.json()) as T);
    } catch {
      throw new ApiError("malformed", "The backend returned an unreadable response.");
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      // An external abort is a deliberate cancellation, not a timeout.
      if (signal?.aborted) throw new ApiError("timeout", "Request cancelled.");
      throw new ApiError(
        "timeout",
        `The backend did not respond within ${Math.round(timeoutMs / 1000)}s.`
      );
    }
    throw new ApiError(
      "network",
      "Could not reach the backend. Is it running?"
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onExternalAbort);
  }
}

/** Human-readable copy for a failure. Section 14 of the frontend plan. */
export function describeError(err: unknown): { title: string; body: string } {
  if (!(err instanceof ApiError)) {
    return {
      title: "THE PIT CREW HIT A PROBLEM",
      body: "Something went wrong that we did not anticipate. Try again.",
    };
  }

  switch (err.kind) {
    case "network":
      return {
        title: "NO CONNECTION TO THE BACKEND",
        body: "The GridMind API is not reachable. If you are running locally, start the backend and check NEXT_PUBLIC_API_BASE_URL.",
      };
    case "timeout":
      return {
        title: "THE BACKEND WENT QUIET",
        body: "The request took longer than expected. The work may still be running. Try again in a moment.",
      };
    case "rate_limited":
      return {
        title: "EASE OFF THE THROTTLE",
        body: err.retryAfterSeconds
          ? `Too many requests. Try again in about ${err.retryAfterSeconds}s.`
          : "Too many requests right now. Give it a moment and try again.",
      };
    case "not_found":
      return {
        title: "NOTHING HERE",
        body: "We could not find that race or report.",
      };
    case "conflict":
      return {
        title: "ALREADY IN THE PIT LANE",
        body: "That session is already being fetched. Watch the existing job rather than starting another.",
      };
    case "server":
      return {
        title: "THE PIT CREW HIT A PROBLEM",
        body: "The backend failed while handling that request. Try again shortly.",
      };
    case "malformed":
      return {
        title: "UNREADABLE RESPONSE",
        body: "The backend replied with something this version of the UI does not understand.",
      };
    case "client":
    default:
      return {
        title: "THAT REQUEST DID NOT WORK",
        body: err.message,
      };
  }
}
