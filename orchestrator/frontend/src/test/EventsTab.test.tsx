import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { EventsTab } from "../components/events/EventsTab";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue([]),
    createWebSocketTicket: vi.fn().mockResolvedValue({ ticket: "t" }),
    runWebSocketUrl: vi.fn().mockReturnValue("ws://test/1"),
  };
});
import { listEvents } from "../lib/api";
const mockListEvents = listEvents as unknown as ReturnType<typeof vi.fn>;

// Same MockWebSocket trick as useRunWebSocket.test.ts
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
    setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
  }
  close() { this.readyState = 3; this.onclose?.(); }
}
// @ts-expect-error
global.WebSocket = MockWebSocket;

beforeEach(() => { MockWebSocket.instances = []; });

function push(data: unknown) {
  MockWebSocket.instances[0].onmessage?.({ data: JSON.stringify(data) });
}

function mkEvent(o: Record<string, unknown> = {}) {
  return {
    id: 1, event_type: "x", phase: "consume", task_name: "t",
    agent_name: "vuln-analyst", summary: "did a thing",
    created_at: "2026-04-17T12:00:00Z",
    kind: "case_done", level: "info", payload: {},
    ...o,
  };
}

describe("EventsTab", () => {
  it("appends incoming WS frames to the stream", async () => {
    render(<EventsTab token="t" projectId={1} runId={2} />);
    await new Promise((r) => setTimeout(r, 5));
    push({ type: "event.created", project_id: 1, run_id: 2, event: mkEvent({ id: 1, summary: "hello world" }) });
    await waitFor(() => screen.getByText("hello world"));
  });

  it("filters by level", async () => {
    render(<EventsTab token="t" projectId={1} runId={2} />);
    await new Promise((r) => setTimeout(r, 5));
    push({ type: "event.created", project_id: 1, run_id: 2, event: mkEvent({ id: 1, summary: "info-line", level: "info" }) });
    push({ type: "event.created", project_id: 1, run_id: 2, event: mkEvent({ id: 2, summary: "error-line", level: "error" }) });
    await waitFor(() => screen.getByText("info-line"));
    await userEvent.selectOptions(screen.getByLabelText("Level"), "error");
    await waitFor(() => expect(screen.queryByText("info-line")).not.toBeInTheDocument());
    expect(screen.getByText("error-line")).toBeInTheDocument();
  });

  it("pause button halts incoming frames", async () => {
    render(<EventsTab token="t" projectId={1} runId={2} />);
    await new Promise((r) => setTimeout(r, 5));
    push({ type: "event.created", project_id: 1, run_id: 2, event: mkEvent({ id: 1, summary: "first" }) });
    await waitFor(() => screen.getByText("first"));
    await userEvent.click(screen.getByRole("button", { name: /Pause/i }));
    push({ type: "event.created", project_id: 1, run_id: 2, event: mkEvent({ id: 2, summary: "blocked" }) });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("blocked")).not.toBeInTheDocument();
    expect(screen.getByText("first")).toBeInTheDocument();
  });

  it("caps at 500 events", async () => {
    render(<EventsTab token="t" projectId={1} runId={2} />);
    await new Promise((r) => setTimeout(r, 5));
    for (let i = 1; i <= 550; i++) {
      push({
        type: "event.created", project_id: 1, run_id: 2,
        event: mkEvent({ id: i, summary: `line-${i}` }),
      });
    }
    // The oldest 50 should have been dropped.
    await waitFor(() => screen.getByText("line-550"));
    expect(screen.queryByText("line-1")).not.toBeInTheDocument();
    expect(screen.queryByText("line-51")).toBeInTheDocument();
  });

  it("pause freezes REST seed — new events from listEvents do not appear while paused", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // First call (initial seed) returns nothing; second call returns a new event.
    mockListEvents.mockResolvedValueOnce([]);
    const newEvent = mkEvent({ id: 99, summary: "seed-while-paused" });
    mockListEvents.mockResolvedValue([newEvent]);

    render(<EventsTab token="t" projectId={1} runId={2} />);

    // Let initial seed settle.
    await act(async () => { await Promise.resolve(); });

    // Click Pause.
    await userEvent.click(screen.getByRole("button", { name: /Pause/i }));

    // Advance past the 15s REST poll interval.
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    // The event from the REST seed must NOT appear while paused.
    expect(screen.queryByText("seed-while-paused")).not.toBeInTheDocument();

    vi.useRealTimers();
  });

  it("pause drops an in-flight REST seed response that resolves after pause is enabled", async () => {
    let resolveSeed: ((value: ReturnType<typeof mkEvent>[]) => void) | null = null;
    mockListEvents.mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveSeed = resolve;
      }),
    );

    render(<EventsTab token="t" projectId={1} runId={2} />);
    await act(async () => { await Promise.resolve(); });

    await userEvent.click(screen.getByRole("button", { name: /Pause/i }));

    await act(async () => {
      resolveSeed?.([mkEvent({ id: 101, summary: "late-seed" })]);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText("late-seed")).not.toBeInTheDocument();
  });

  it("shows seed error banner when REST history fetch fails and clears it on recovery", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // First call rejects.
    mockListEvents.mockRejectedValueOnce(new Error("denied"));

    render(<EventsTab token="t" projectId={1} runId={2} />);

    // Let the initial fetch settle.
    await act(async () => { await Promise.resolve(); });

    // Banner should appear with the error message.
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("denied"),
    );

    // Second poll succeeds — banner should clear.
    mockListEvents.mockResolvedValueOnce([]);
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      // Drain microtasks so the resolved promise settles.
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );

    vi.useRealTimers();
  });
});
