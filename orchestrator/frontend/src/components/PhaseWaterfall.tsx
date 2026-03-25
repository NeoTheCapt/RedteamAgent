import type { EventRecord } from "../lib/api";

const PHASES = ["recon", "collect", "consume-test", "exploit", "report"];

type PhaseWaterfallProps = {
  events: EventRecord[];
};

function phaseLabel(phase: string) {
  switch (phase) {
    case "consume-test":
      return "Consume & Test";
    default:
      return phase.charAt(0).toUpperCase() + phase.slice(1);
  }
}

function phaseState(events: EventRecord[], phase: string) {
  const relevant = events.filter((event) => event.phase === phase);
  if (relevant.some((event) => event.event_type === "phase.completed")) {
    return "completed";
  }
  if (relevant.some((event) => event.event_type === "phase.started")) {
    return "active";
  }
  return "pending";
}

export function PhaseWaterfall({ events }: PhaseWaterfallProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Phase waterfall</h2>
        <p className="meta-text">Five-phase autonomous workflow</p>
      </div>
      <div className="waterfall">
        {PHASES.map((phase) => {
          const state = phaseState(events, phase);
          const taskCount = events.filter((event) => event.phase === phase && event.event_type.startsWith("task.")).length;
          return (
            <article key={phase} className={`phase-card phase-${state}`}>
              <p className="eyebrow">{state}</p>
              <h3>{phaseLabel(phase)}</h3>
              <p className="meta-text">{taskCount} task events</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
