import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useRunWebSocket } from "../lib/useRunWebSocket";

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
