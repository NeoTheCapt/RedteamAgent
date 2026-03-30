import type { EventRecord } from "../lib/api";

type TaskTimelineProps = {
  events: EventRecord[];
  selectedAgent: string | null;
};

const AGENT_PHASES: Record<string, string> = {
  operator: "coordination",
  "recon-specialist": "recon",
  "source-analyzer": "unassigned",
  "vulnerability-analyst": "consume-test",
  "exploit-developer": "exploit",
  "osint-analyst": "exploit",
  "report-writer": "report",
};

function titleCasePhase(phase: string, agentName: string) {
  const normalized = !phase || phase === "unknown" ? AGENT_PHASES[agentName] ?? "unassigned" : phase;
  if (normalized === "consume-test") return "Consume & Test";
  if (normalized === "coordination") return "Coordination";
  if (normalized === "unassigned") return "Unassigned";
  return normalized
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function TaskTimeline({ events, selectedAgent }: TaskTimelineProps) {
  const taskEvents = [...events.filter((event) => event.event_type.startsWith("task."))]
    .filter((event) => (selectedAgent ? event.agent_name === selectedAgent : true))
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);

  return (
    <section className="panel timeline-panel tall-panel">
      <div className="panel-header">
        <div>
          <h2>{selectedAgent ? `Activities · ${selectedAgent}` : "All activities"}</h2>
          <p className="meta-text">Task-level execution feed across the current mission.</p>
        </div>
      </div>
      <div className="timeline">
        {taskEvents.map((event) => (
          <article key={event.id} className="timeline-row">
            <div className="timeline-pill">{titleCasePhase(event.phase, event.agent_name)}</div>
            <div className="timeline-body">
              <div className="timeline-title-row">
                <strong>{event.task_name || event.agent_name}</strong>
                <span className="meta-text">{event.agent_name}</span>
              </div>
              <p>{event.summary}</p>
              <p className="meta-text">
                {event.event_type} · {event.created_at}
              </p>
            </div>
          </article>
        ))}
        {taskEvents.length === 0 ? <p className="empty-state">No activities yet for this filter.</p> : null}
      </div>
    </section>
  );
}
