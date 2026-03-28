import type { RunSummary } from "../lib/api";

type SubagentBoardProps = {
  summary: RunSummary | null;
  selectedAgent: string | null;
  onSelectAgent: (agentName: string | null) => void;
};

const AGENT_DESCRIPTIONS: Record<string, string> = {
  operator: "Coordinates the full engagement workflow and phase transitions.",
  "recon-specialist": "Fingerprints reachable hosts, services, and exposed paths.",
  "source-analyzer": "Reviews HTML and JavaScript for endpoints, secrets, and surfaces.",
  "vulnerability-analyst": "Tests queued cases and validates likely weaknesses.",
  "exploit-developer": "Attempts exploit chains and validates practical impact.",
  "osint-analyst": "Expands external intelligence and infrastructure context.",
  "report-writer": "Builds the final report and evidence summary.",
};

const AGENT_PHASES: Record<string, string> = {
  operator: "coordination",
  "recon-specialist": "recon",
  "source-analyzer": "recon",
  "vulnerability-analyst": "consume-test",
  "exploit-developer": "exploit",
  "osint-analyst": "exploit",
  "report-writer": "report",
};

function titleCasePhase(phase: string) {
  const normalized = !phase || phase === "unknown" ? "unassigned" : phase;
  if (normalized === "consume-test") return "Consume & Test";
  if (normalized === "unassigned") return "Unassigned";
  if (normalized === "coordination") return "Coordination";
  return normalized
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function SubagentBoard({ summary, selectedAgent, onSelectAgent }: SubagentBoardProps) {
  const agents = summary?.agents ?? [];

  return (
    <section className="panel subagent-panel tall-panel">
      <div className="panel-header">
        <div>
          <h2>Agents</h2>
          <p className="meta-text">Stable worker roster with role, phase, and current posture.</p>
        </div>
        <button
          className={`ghost-button compact-button ${selectedAgent === null ? "filter-button-active" : ""}`}
          onClick={() => onSelectAgent(null)}
        >
          All activities
        </button>
      </div>
      <div className="subagent-list">
        {agents.map((agent) => {
          const displayPhase = agent.phase === "unknown" ? AGENT_PHASES[agent.agent_name] ?? "unassigned" : agent.phase;
          const description = AGENT_DESCRIPTIONS[agent.agent_name] ?? "Supports engagement execution.";
          return (
            <button
              key={agent.agent_name}
              className={`subagent-row subagent-button ${selectedAgent === agent.agent_name ? "subagent-selected" : ""}`}
              onClick={() => onSelectAgent(agent.agent_name)}
            >
              <div className="subagent-heading">
                <div>
                  <strong>{agent.agent_name}</strong>
                  <p className="meta-text">{titleCasePhase(displayPhase)}</p>
                </div>
                <span className={`status-pill status-${agent.status === "idle" ? "queued" : agent.status}`}>
                  {agent.status}
                </span>
              </div>
              <p>{description}</p>
              <p className="meta-text">{agent.task_name || "No active task"}</p>
              <p className="muted-text">{agent.summary || "No activity yet."}</p>
            </button>
          );
        })}
        {agents.length === 0 ? <p className="empty-state">No agent activity yet.</p> : null}
      </div>
    </section>
  );
}
