import { useEffect, useRef } from "react";
import { createWebSocketTicket, runWebSocketUrl } from "./api";

export type RunWsFrame = {
  type: string;
  project_id: number;
  run_id: number;
  event?: {
    id: number;
    event_type: string;
    phase: string;
    task_name: string;
    agent_name: string;
    summary: string;
    created_at: string;
    kind?: string;
    level?: string;
    payload?: unknown;
  };
  // Other envelopes (e.g. status updates) may have different shapes.
  [extra: string]: unknown;
};

type Options = {
  enabled?: boolean;
};

/**
 * Open a per-run WebSocket connection. Delivers each decoded frame to
 * `onFrame`. Reconnects on drop with 2/4/8s backoff. Cleanup aborts pending
 * reconnects and closes the socket.
 *
 * Errors are logged; caller does not see them (frames just stop arriving
 * until a reconnect succeeds).
 */
export function useRunWebSocket(
  token: string,
  projectId: number,
  runId: number,
  onFrame: (frame: RunWsFrame) => void,
  { enabled = true }: Options = {},
): void {
  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let attempt = 0;

    async function connect() {
      if (cancelled) return;

      // Guard so both onerror and onclose cannot both schedule a reconnect.
      let reconnectScheduled = false;

      function scheduleReconnect() {
        if (cancelled || reconnectScheduled) return;
        reconnectScheduled = true;
        const delay = Math.min(8000, 2000 * Math.pow(2, Math.min(attempt, 2)));
        attempt += 1;
        reconnectTimer = window.setTimeout(() => void connect(), delay);
      }

      try {
        const { ticket } = await createWebSocketTicket(token);
        if (cancelled) return;
        const url = runWebSocketUrl(projectId, runId, ticket);
        ws = new WebSocket(url);
        ws.onopen = () => { attempt = 0; };
        ws.onmessage = (ev) => {
          let frame: RunWsFrame;
          try {
            frame = JSON.parse(ev.data);
          } catch {
            return;
          }
          onFrameRef.current(frame);
        };
        ws.onclose = () => { scheduleReconnect(); };
        ws.onerror = () => { scheduleReconnect(); };
      } catch (err) {
        if (cancelled) return;
        console.warn("[useRunWebSocket] ticket or open failed:", err);
        scheduleReconnect();
      }
    }

    void connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (ws !== null) {
        try { ws.close(); } catch { /* ignore */ }
      }
    };
  }, [token, projectId, runId, enabled]);
}
