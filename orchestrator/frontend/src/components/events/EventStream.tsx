import { useEffect, useRef } from "react";
import type { EventRecord } from "../../lib/api";
import { parseServerTimestamp } from "../../lib/format";

export type DisplayEvent = EventRecord & {
  kind?: string;
  level?: string;
  payload?: unknown;
};

type EventStreamProps = {
  events: DisplayEvent[];
  autoScroll: boolean;
  onAutoScrollChange: (on: boolean) => void;
};

export function EventStream({ events, autoScroll, onAutoScrollChange }: EventStreamProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !autoScroll) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length, autoScroll]);

  function onScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    if (atBottom !== autoScroll) onAutoScrollChange(atBottom);
  }

  return (
    <div className="event-stream" ref={scrollRef} onScroll={onScroll}>
      {events.length === 0 && (
        <div className="event-stream__empty">No events match the current filters.</div>
      )}
      {events.map((e) => (
        <div key={e.id} className={`event-row event-row--${(e.level ?? "info").toLowerCase()}`}>
          <span className="event-row__time">{formatTime(e.created_at)}</span>
          <span className="event-row__kind">{e.kind ?? e.event_type}</span>
          <span className="event-row__agent">{e.agent_name}</span>
          <span className="event-row__phase">{e.phase}</span>
          <span className="event-row__summary">{e.summary}</span>
        </div>
      ))}
    </div>
  );
}

function formatTime(iso: string): string {
  const d = parseServerTimestamp(iso);
  if (!d) return "—";
  return d.toLocaleTimeString([], { hour12: false });
}
