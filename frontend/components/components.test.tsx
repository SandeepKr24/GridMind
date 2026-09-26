// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { ChatMessage } from "@/lib/api/types";
import { AsyncBoundary, isNotFound } from "./AsyncBoundary";
import { ChatMessageView } from "./chat/ChatMessage";
import { LoadingPit, type LoadingPitProps } from "./LoadingPit";
import { SettingsProvider } from "./SettingsProvider";
import { ErrorState, IngestionBadge } from "./ui/primitives";

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const withSettings = (ui: ReactNode) => render(<SettingsProvider>{ui}</SettingsProvider>);

function pit(props: Partial<LoadingPitProps> = {}) {
  return withSettings(
    <LoadingPit
      active
      stage="fetching"
      stageIndex={1}
      elapsedSeconds={3}
      {...props}
    />
  );
}

describe("LoadingPit", () => {
  it("renders nothing when inactive", () => {
    pit({ active: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the current backend stage and announces it", () => {
    pit();
    expect(screen.getByText("Fetching timing data...")).toBeTruthy();
    expect(screen.getByText("Stage 2 of 5 · lights advance on backend stages")).toBeTruthy();
    expect(document.querySelector("[aria-live]")?.textContent).toBe("Fetching timing data");
  });

  it("proves liveness during a long fetch", () => {
    pit({ elapsedSeconds: 40 });
    expect(screen.getByText(/Working, not frozen. 40s elapsed/)).toBeTruthy();
    expect(screen.getByText("T+00:40")).toBeTruthy();
  });

  it("shows an overdue job as taking longer, not as failed", () => {
    pit({ overdue: true, elapsedSeconds: 160 });
    expect(screen.getByText("TAKING LONGER THAN EXPECTED")).toBeTruthy();
    expect(screen.queryByText("RETRY JOB")).toBeNull();
  });

  it("shows a failure with its message and a retry", () => {
    const onRetry = vi.fn();
    pit({ failed: true, error: "Timing API unavailable", onRetry, onDismiss: vi.fn() });

    expect(screen.getByText("JOB FAILED")).toBeTruthy();
    expect(screen.getByText("Timing API unavailable")).toBeTruthy();
    fireEvent.click(screen.getByText("RETRY JOB"));
    expect(onRetry).toHaveBeenCalled();
    expect(screen.getByText("DISMISS")).toBeTruthy();
  });

  it("moves focus into the dialog and sends the job to the background on Escape", () => {
    const onDismiss = vi.fn();
    pit({ onDismiss });

    const panel = document.activeElement as HTMLElement;
    expect(screen.getByRole("dialog").contains(panel)).toBe(true);

    fireEvent.keyDown(panel, { key: "Escape" });
    expect(onDismiss).toHaveBeenCalled();
  });

  it("keeps Tab inside the dialog", () => {
    pit({ failed: true, onRetry: vi.fn(), onDismiss: vi.fn() });
    const retry = screen.getByText("RETRY JOB");
    const dismiss = screen.getByText("DISMISS");

    dismiss.focus();
    fireEvent.keyDown(dismiss, { key: "Tab" });
    expect(document.activeElement).toBe(retry);

    fireEvent.keyDown(retry, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(dismiss);
  });

  it("returns focus to where it was when it closes", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    const { rerender } = withSettings(
      <LoadingPit active stage="resolving" stageIndex={0} elapsedSeconds={0} />
    );
    expect(document.activeElement).not.toBe(opener);

    act(() => {
      rerender(
        <SettingsProvider>
          <LoadingPit active={false} stage="resolving" stageIndex={0} elapsedSeconds={0} />
        </SettingsProvider>
      );
    });
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

describe("ChatMessageView", () => {
  const assistant = (extra: Partial<ChatMessage>): ChatMessage => ({
    id: "m1",
    role: "assistant",
    text: "Norris gained the most.",
    ...extra,
  });

  it("shows which race the agent inferred", () => {
    render(
      <ChatMessageView
        message={assistant({
          entities: {
            year: 2025,
            round: 15,
            grand_prix: "Italian Grand Prix",
            session_type: "race",
            drivers: [],
          },
        })}
      />
    );
    expect(screen.getByText("2025 · Italian Grand Prix · Race")).toBeTruthy();
  });

  it("draws bars and a table for a single numeric measure", () => {
    render(
      <ChatMessageView
        message={assistant({
          table: { columns: ["DRIVER", "GAINED"], rows: [["NOR", "5"], ["LEC", "2"]] },
          sources: ["classification"],
        })}
      />
    );
    expect(screen.getByText("GAINED by DRIVER")).toBeTruthy();
    expect(screen.getAllByText("NOR")).toHaveLength(2);
    expect(screen.getByText("SOURCE · classification")).toBeTruthy();
  });

  it("draws no chart for a user message", () => {
    render(<ChatMessageView message={{ id: "u1", role: "user", text: "Who won?" }} />);
    expect(screen.getByText("YOU")).toBeTruthy();
    expect(document.querySelector("figure")).toBeNull();
  });

  it("draws negative values to the left", () => {
    render(
      <ChatMessageView
        message={assistant({
          table: { columns: ["DRIVER", "DELTA"], rows: [["NOR", "-3"], ["LEC", "2"]] },
        })}
      />
    );
    expect(screen.getAllByText("-3").length).toBeGreaterThan(0);
  });
});

describe("ChatMessageView team columns", () => {
  const reply = (columns: string[], rows: string[][]): ChatMessage => ({
    id: "t1",
    role: "assistant",
    text: "Here you go.",
    table: { columns, rows },
  });

  it("marks team names in a Team column", () => {
    render(<ChatMessageView message={reply(["Driver", "Team"], [["Max Verstappen", "Red Bull Racing"]])} />);

    expect(screen.getByText("Red Bull Racing")).toBeTruthy();
    expect(screen.getAllByTestId(/team-(logo|colour)/)).toHaveLength(1);
  });

  it("leaves other columns, and unknown values in a Team column, as plain text", () => {
    render(
      <ChatMessageView
        message={reply(["Driver", "Constructor"], [["Ferrari", "—"], ["Lewis Hamilton", "Unknown"]])}
      />
    );

    // "Ferrari" sits in the Driver column, so it is not decorated.
    expect(screen.queryAllByTestId(/team-(logo|colour)/)).toHaveLength(0);
  });
});

describe("AsyncBoundary", () => {
  it("shows a skeleton while loading", () => {
    render(
      <AsyncBoundary state={{ status: "loading", data: null, error: null }} loading={<p>wait</p>}>
        {() => <p>data</p>}
      </AsyncBoundary>
    );
    expect(screen.getByText("wait")).toBeTruthy();
  });

  it("shows the error copy for the failure kind, with retry", () => {
    const reload = vi.fn();
    render(
      <AsyncBoundary
        state={{ status: "error", data: null, error: new ApiError("network", "x"), reload }}
      >
        {() => <p>data</p>}
      </AsyncBoundary>
    );
    expect(screen.getByText("NO CONNECTION TO THE BACKEND")).toBeTruthy();
    fireEvent.click(screen.getByText("TRY AGAIN"));
    expect(reload).toHaveBeenCalled();
  });

  it("renders data on success", () => {
    render(
      <AsyncBoundary state={{ status: "success", data: "Monza", error: null }}>
        {(d) => <p>{d}</p>}
      </AsyncBoundary>
    );
    expect(screen.getByText("Monza")).toBeTruthy();
  });

  it("isNotFound only matches 404", () => {
    expect(isNotFound(new ApiError("not_found", "x"))).toBe(true);
    expect(isNotFound(new ApiError("server", "x"))).toBe(false);
    expect(isNotFound(new Error("x"))).toBe(false);
  });
});

describe("primitives", () => {
  it.each(["ingested", "available", "upcoming"] as const)(
    "IngestionBadge labels %s in text, not only colour",
    (state) => {
      render(<IngestionBadge state={state} />);
      expect(screen.getByText(state.toUpperCase())).toBeTruthy();
    }
  );

  it("ErrorState is announced as an alert", () => {
    render(<ErrorState title="T" body="B" />);
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});
