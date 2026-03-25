import type { EventRecord } from "../lib/api";

type TaskTimelineProps = {
  events: EventRecord[];
};

export function TaskTimeline({ events }: TaskTimelineProps) {
  const taskEvents = events.filter((event) => event.event_type.startsWith("task."));

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Task timeline</h2>
        <p className="meta-text">Worker activity and summaries</p>
      </div>
      <div className="timeline">
        {taskEvents.map((event) => (
          <article key={event.id} className="timeline-row">
            <div className="timeline-pill">{event.phase}</div>
            <div className="timeline-body">
              <div className="timeline-title-row">
                <strong>{event.task_name}</strong>
                <span className="meta-text">{event.agent_name}</span>
              </div>
              <p>{event.summary}</p>
              <p className="meta-text">{event.event_type}</p>
            </div>
          </article>
        ))}
        {taskEvents.length === 0 ? <p className="empty-state">No task events yet.</p> : null}
      </div>
    </section>
  );
}
