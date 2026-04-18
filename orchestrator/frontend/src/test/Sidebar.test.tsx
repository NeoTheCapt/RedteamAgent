import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Sidebar } from "../components/shell/Sidebar";
import type { Run } from "../lib/api";

function mkRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1, target: "http://example.test", status: "running",
    engagement_root: "/x", created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
    ...overrides,
  } as Run;
}

describe("Sidebar", () => {
  it("renders runs with target, status, id", () => {
    const runs = [mkRun({ id: 1, target: "juice-shop:8000", status: "running" })];
    render(
      <Sidebar
        runs={runs}
        selectedRunId={null}
        onSelectRun={vi.fn()}
        onNewRun={vi.fn()}
        username="alice"
        onLogout={vi.fn()}
        projectIdForRun={() => 1}
      />
    );
    expect(screen.getByText("juice-shop:8000")).toBeInTheDocument();
    expect(screen.getByText("#r-1")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
  });

  it("highlights the selected run via aria-current", () => {
    const runs = [
      mkRun({ id: 1, target: "a" }),
      mkRun({ id: 2, target: "b" }),
    ];
    render(
      <Sidebar runs={runs} selectedRunId={2} onSelectRun={vi.fn()} onNewRun={vi.fn()}
        username="u" onLogout={vi.fn()} projectIdForRun={() => 1}
      />
    );
    const buttons = screen.getAllByRole("button");
    const bBtn = buttons.find((b) => b.textContent?.includes("b"));
    expect(bBtn).toHaveAttribute("aria-current", "true");
  });

  it("fires onSelectRun with projectId when a run is clicked", async () => {
    const onSelect = vi.fn();
    const runs = [mkRun({ id: 42, target: "x" })];
    render(<Sidebar runs={runs} selectedRunId={null} onSelectRun={onSelect}
      onNewRun={vi.fn()} username="u" onLogout={vi.fn()} projectIdForRun={() => 7}
    />);
    await userEvent.click(screen.getByText("x"));
    expect(onSelect).toHaveBeenCalledWith(7, 42);
  });

  it("fires onNewRun when + NEW RUN is clicked", async () => {
    const onNew = vi.fn();
    render(<Sidebar runs={[]} selectedRunId={null} onSelectRun={vi.fn()} onNewRun={onNew}
      username="u" onLogout={vi.fn()} projectIdForRun={() => 1}
    />);
    await userEvent.click(screen.getByText("+ NEW RUN"));
    expect(onNew).toHaveBeenCalled();
  });

  it("renders SQLite-format updated_at without Invalid Date (Bug 5)", () => {
    // SQLite timestamps are "YYYY-MM-DD HH:MM:SS" (no T, no TZ).
    // Safari's new Date() returns Invalid Date for that format.
    // parseServerTimestamp coerces it to a valid UTC Date.
    const runs = [mkRun({ updated_at: "2026-04-17 12:34:56" })];
    render(
      <Sidebar runs={runs} selectedRunId={null} onSelectRun={vi.fn()} onNewRun={vi.fn()}
        username="u" onLogout={vi.fn()} projectIdForRun={() => 1}
      />
    );
    const timeEl = document.querySelector("time");
    expect(timeEl?.textContent).not.toContain("Invalid Date");
    // The timestamp is valid, so it should render a real time (not the fallback "—").
    expect(timeEl?.textContent).toMatch(/^updated \d/);
  });
});
