import { useCallback, useMemo, useRef, useState } from "react";
import { listEvents } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { useRunWebSocket, type RunWsFrame } from "../../lib/useRunWebSocket";
import { EventFilters, type EventFilterValues } from "./EventFilters";
import { EventStream, type DisplayEvent } from "./EventStream";
import "./events.css";

type EventsTabProps = {
  token: string;
  projectId: number;
  runId: number;
};

const MAX_EVENTS = 500;

function emptyFilters(): EventFilterValues {
  return { level: "", kind: "", source: "", search: "" };
}

export function EventsTab({ token, projectId, runId }: EventsTabProps) {
  const [events, setEvents] = useState<DisplayEvent[]>([]);
  const [filters, setFilters] = useState<EventFilterValues>(emptyFilters());
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [seedError, setSeedError] = useState<string | null>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // Initial + periodic seed from REST (captures whatever we missed while
  // the socket was reconnecting).
  useAutoRefresh(
    async (signal) => {
      try {
        const seed = await listEvents(token, projectId, runId);
        if (signal.aborted) return;
        setEvents((prev) => mergeEvents(prev, seed as DisplayEvent[]));
        setSeedError(null);
      } catch (err) {
        if (signal.aborted) return;
        setSeedError(err instanceof Error ? err.message : String(err));
      }
    },
    [token, projectId, runId],
    { intervalMs: 15_000 },
  );

  const onFrame = useCallback((frame: RunWsFrame) => {
    if (pausedRef.current) return;
    const ev = frame.event;
    if (!ev) return;
    setEvents((prev) => appendEvent(prev, ev as DisplayEvent));
  }, []);

  useRunWebSocket(token, projectId, runId, onFrame);

  const filtered = useMemo(
    () => events.filter((e) => matchesFilters(e, filters)),
    [events, filters],
  );

  return (
    <div className="events" data-testid="events-tab">
      <EventFilters
        value={filters}
        onChange={setFilters}
        totalCount={events.length}
        filteredCount={filtered.length}
        paused={paused}
        onTogglePause={() => setPaused((p) => !p)}
      />
      {seedError && (
        <div className="events__seed-warning" role="status" aria-live="polite">
          Event history refresh failed: {seedError}. Live events continue.
        </div>
      )}
      <EventStream
        events={filtered}
        autoScroll={autoScroll}
        onAutoScrollChange={setAutoScroll}
      />
    </div>
  );
}

function appendEvent(prev: DisplayEvent[], next: DisplayEvent): DisplayEvent[] {
  if (prev.some((e) => e.id === next.id)) return prev;
  const merged = [...prev, next];
  return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
}

function mergeEvents(prev: DisplayEvent[], seed: DisplayEvent[]): DisplayEvent[] {
  if (prev.length === 0) return seed.slice(-MAX_EVENTS);
  const byId = new Map(prev.map((e) => [e.id, e]));
  for (const e of seed) byId.set(e.id, e);
  const merged = Array.from(byId.values()).sort((a, b) => a.id - b.id);
  return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
}

function matchesFilters(e: DisplayEvent, f: EventFilterValues): boolean {
  if (f.level && (e.level ?? "info") !== f.level) return false;
  if (f.kind && (e.kind ?? "legacy") !== f.kind) return false;
  if (f.source && !e.agent_name.toLowerCase().includes(f.source.toLowerCase())) return false;
  if (f.search) {
    const q = f.search.toLowerCase();
    if (!e.summary.toLowerCase().includes(q)
        && !e.task_name.toLowerCase().includes(q)
        && !(e.phase ?? "").toLowerCase().includes(q)) {
      return false;
    }
  }
  return true;
}
