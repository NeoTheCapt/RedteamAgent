import type { RunSummary } from "../lib/api";

type PhaseWaterfallProps = {
  summary: RunSummary | null;
};

const PHASE_DESCRIPTIONS: Record<string, string> = {
  recon: "Fingerprint hosts, services, domains, and initial attack surface.",
  collect: "Harvest source artifacts, routes, secrets, and actionable endpoints.",
  "consume-test": "Validate cases, test hypotheses, and escalate likely weaknesses.",
  exploit: "Confirm practical impact and attempt bounded exploit chains.",
  report: "Synthesize evidence, findings, and remediation guidance.",
};

export function PhaseWaterfall({ summary }: PhaseWaterfallProps) {
  return (
    <section className="panel waterfall-panel">
      <div className="panel-header">
        <h2>Phase waterfall</h2>
        <p className="meta-text">Five-phase autonomous workflow with live phase state</p>
      </div>
      <div className="waterfall">
        {(summary?.phases ?? []).map((phase) => {
          const state = phase.state;
          const displayState =
            phase.phase === "recon" && phase.task_events === 0 && phase.active_agents === 0 && !phase.latest_summary
              ? "initializing"
              : state;
          return (
            <article key={phase.phase} className={`phase-card phase-${state} ${state === "active" ? "phase-pulse" : ""}`}>
              <div className="phase-card-header">
                <p className="eyebrow">{displayState}</p>
                <span className={`phase-state-dot phase-state-${state}`} />
              </div>
              <h3>{phase.label}</h3>
              <p className="muted-text">{PHASE_DESCRIPTIONS[phase.phase] ?? "No description available."}</p>
              <p className="meta-text">
                {phase.task_events} task events, {phase.active_agents} active agents
              </p>
              <p className="muted-text">{phase.latest_summary || "No phase summary yet"}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
