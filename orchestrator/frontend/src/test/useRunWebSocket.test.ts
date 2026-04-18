import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useRunWebSocket } from "../lib/useRunWebSocket";
import { createWebSocketTicket } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    createWebSocketTicket: vi.fn().mockResolvedValue({ ticket: "t1" }),
    runWebSocketUrl: vi.fn().mockImplementation(
      (_p: number, _r: number, ticket: string) => `ws://localhost/ws?t=${ticket}`,
    ),
  };
});

// Replace global WebSocket with a stub we control.
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // Fire open asynchronously
    setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
  }
  close() { this.readyState = 3; this.onclose?.(); }
  push(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

// @ts-expect-error — override for test
global.WebSocket = MockWebSocket;

beforeEach(() => {
  MockWebSocket.instances = [];
});

describe("useRunWebSocket", () => {
  it("opens a socket via ticket + url helpers", async () => {
    const onFrame = vi.fn();
    renderHook(() => useRunWebSocket("tok", 1, 2, onFrame));
    // Wait for ticket promise + ctor
    await new Promise((r) => setTimeout(r, 5));
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost/ws?t=t1");
  });

  it("delivers decoded frames to onFrame", async () => {
    const onFrame = vi.fn();
    renderHook(() => useRunWebSocket("tok", 1, 2, onFrame));
    await new Promise((r) => setTimeout(r, 5));
    MockWebSocket.instances[0].push({
      type: "event.created", project_id: 1, run_id: 2,
      event: { id: 1, event_type: "x", phase: "y", task_name: "t",
        agent_name: "a", summary: "s", created_at: "z" },
    });
    expect(onFrame).toHaveBeenCalledTimes(1);
    expect(onFrame.mock.calls[0][0].type).toBe("event.created");
  });

  it("does not connect when enabled=false", async () => {
    const onFrame = vi.fn();
    renderHook(() =>
      useRunWebSocket("tok", 1, 2, onFrame, { enabled: false }),
    );
    await new Promise((r) => setTimeout(r, 5));
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("closes the socket on unmount", async () => {
    const onFrame = vi.fn();
    const { unmount } = renderHook(() =>
      useRunWebSocket("tok", 1, 2, onFrame),
    );
    await new Promise((r) => setTimeout(r, 5));
    const sock = MockWebSocket.instances[0];
    unmount();
    expect(sock.readyState).toBe(3);
  });

  it("ignores malformed frames without crashing", async () => {
    const onFrame = vi.fn();
    renderHook(() => useRunWebSocket("tok", 1, 2, onFrame));
    await new Promise((r) => setTimeout(r, 5));
    MockWebSocket.instances[0].onmessage?.({ data: "not valid json" });
    expect(onFrame).not.toHaveBeenCalled();
  });
});

describe("reconnect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.mocked(createWebSocketTicket).mockResolvedValue({ ticket: "t1" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reconnect delay progression: delays double after each drop (2s → 4s → 8s)", async () => {
    renderHook(() => useRunWebSocket("tok", 1, 2, vi.fn()));

    // Let the ticket promise resolve and the first WS constructor run.
    await act(async () => {
      await Promise.resolve(); // ticket microtask
      vi.advanceTimersByTime(0); // MockWebSocket setTimeout(onopen, 0)
    });

    expect(MockWebSocket.instances.length).toBe(1);

    // Drop 1 → should reconnect after 2000 ms (attempt was 0).
    act(() => { MockWebSocket.instances[0].onclose?.(); });
    expect(MockWebSocket.instances.length).toBe(1); // reconnect not fired yet

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve(); // ticket microtask for reconnect
      vi.advanceTimersByTime(0); // onopen timer
    });
    expect(MockWebSocket.instances.length).toBe(2);

    // Drop 2 → should reconnect after 4000 ms (attempt is now 1).
    act(() => { MockWebSocket.instances[1].onclose?.(); });

    await act(async () => {
      vi.advanceTimersByTime(4000);
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(MockWebSocket.instances.length).toBe(3);

    // Drop 3 → should reconnect after 8000 ms (attempt is now 2).
    act(() => { MockWebSocket.instances[2].onclose?.(); });

    await act(async () => {
      vi.advanceTimersByTime(8000);
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(MockWebSocket.instances.length).toBe(4);
  });

  it("attempt resets on onopen: drop after successful open schedules 2s reconnect", async () => {
    renderHook(() => useRunWebSocket("tok", 1, 2, vi.fn()));

    // First connect + open.
    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(0); // fires onopen → attempt resets to 0
    });
    expect(MockWebSocket.instances.length).toBe(1);

    // Simulate a prior drop so attempt would be > 0 if onopen hadn't reset it.
    // Instead drop once to bump attempt after open resets it.
    act(() => { MockWebSocket.instances[0].onclose?.(); });

    // With attempt=0 (reset by onopen), delay should be 2000 ms.
    // Advancing 1999 ms should not yet produce a new socket.
    await act(async () => { vi.advanceTimersByTime(1999); });
    expect(MockWebSocket.instances.length).toBe(1);

    // Advancing 1 more ms triggers the reconnect.
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(MockWebSocket.instances.length).toBe(2);
  });

  it("ticket refresh per reconnect: createWebSocketTicket called once per connect attempt", async () => {
    const ticketMock = vi.mocked(createWebSocketTicket);
    ticketMock.mockClear();

    renderHook(() => useRunWebSocket("tok", 1, 2, vi.fn()));

    // First connect.
    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(ticketMock).toHaveBeenCalledTimes(1);

    // First reconnect.
    act(() => { MockWebSocket.instances[0].onclose?.(); });
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(ticketMock).toHaveBeenCalledTimes(2);

    // Second reconnect.
    act(() => { MockWebSocket.instances[1].onclose?.(); });
    await act(async () => {
      vi.advanceTimersByTime(4000);
      await Promise.resolve();
      vi.advanceTimersByTime(0);
    });
    expect(ticketMock).toHaveBeenCalledTimes(3);
  });
});
