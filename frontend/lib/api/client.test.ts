import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiBaseUrl, describeError, request } from "./client";

const BASE = "http://api.test";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    if (err instanceof ApiError) return err;
    throw err;
  }
  throw new Error("expected the request to fail");
}

describe("request", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", `${BASE}/`);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.useRealTimers();
  });

  it("returns parsed JSON and calls the base URL without a double slash", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));

    const result = await request<{ ok: boolean }>("/api/races");

    expect(result).toEqual({ ok: true });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${BASE}/api/races`);
  });

  it("sends a JSON body on POST", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));

    await request("/api/chat", { method: "POST", body: { message: "hi" } });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ message: "hi" }));
    expect(init?.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(request("/api/x")).resolves.toBeUndefined();
  });

  it("fails as network when no backend URL is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe("network");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("classifies a thrown fetch as network", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe("network");
    expect(err.isTransient).toBe(true);
  });

  it.each([
    [404, "not_found", false],
    [409, "conflict", false],
    [500, "server", true],
    [503, "server", true],
    [400, "client", false],
  ] as const)("classifies HTTP %i as %s", async (status, kind, transient) => {
    fetchMock.mockResolvedValue(jsonResponse(status, { detail: "nope" }));
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe(kind);
    expect(err.status).toBe(status);
    expect(err.message).toBe("nope");
    expect(err.isTransient).toBe(transient);
  });

  it("reads Retry-After on 429", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429, {}, { "Retry-After": "12" }));
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe("rate_limited");
    expect(err.retryAfterSeconds).toBe(12);
  });

  it("ignores a non-numeric Retry-After", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429, {}, { "Retry-After": "soon" }));
    const err = await captureError(request("/api/x"));
    expect(err.retryAfterSeconds).toBeNull();
  });

  it("falls back to the status line when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 502, statusText: "Bad Gateway" }));
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe("server");
    expect(err.message).toBe("Bad Gateway");
  });

  it("classifies an unreadable 200 body as malformed", async () => {
    fetchMock.mockResolvedValue(new Response("not json", { status: 200 }));
    const err = await captureError(request("/api/x"));
    expect(err.kind).toBe("malformed");
  });

  it("times out when the backend does not answer in time", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError"))
          );
        })
    );

    const pending = captureError(request("/api/x", { timeoutMs: 5_000 }));
    await vi.advanceTimersByTimeAsync(5_000);
    const err = await pending;

    expect(err.kind).toBe("timeout");
    expect(err.message).toContain("5s");
  });

  it("treats a caller abort as a cancellation", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError"))
          );
        })
    );

    const pending = captureError(request("/api/x", { signal: controller.signal }));
    controller.abort();
    const err = await pending;

    expect(err.kind).toBe("timeout");
    expect(err.message).toBe("Request cancelled.");
  });
});

describe("apiBaseUrl", () => {
  it("strips trailing slashes", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://a.test///");
    expect(apiBaseUrl()).toBe("http://a.test");
  });
});

describe("describeError", () => {
  it.each([
    ["network", "NO CONNECTION TO THE BACKEND"],
    ["timeout", "THE BACKEND WENT QUIET"],
    ["rate_limited", "EASE OFF THE THROTTLE"],
    ["not_found", "NOTHING HERE"],
    ["conflict", "ALREADY IN THE PIT LANE"],
    ["server", "THE PIT CREW HIT A PROBLEM"],
    ["malformed", "UNREADABLE RESPONSE"],
    ["client", "THAT REQUEST DID NOT WORK"],
  ] as const)("gives %s its own title", (kind, title) => {
    expect(describeError(new ApiError(kind, "detail")).title).toBe(title);
  });

  it("includes the retry hint for a rate limit with Retry-After", () => {
    const { body } = describeError(new ApiError("rate_limited", "x", 429, 30));
    expect(body).toContain("30s");
  });

  it("passes a client error's own message through", () => {
    expect(describeError(new ApiError("client", "Bad season")).body).toBe("Bad season");
  });

  it("handles errors that are not ApiError", () => {
    expect(describeError(new Error("boom")).title).toBe("THE PIT CREW HIT A PROBLEM");
  });
});
