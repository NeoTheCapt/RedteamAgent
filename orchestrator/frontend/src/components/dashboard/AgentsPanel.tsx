import type { Dispatch, RunSummary } from "../../lib/api";
import "./agentsPanel.css";

type AgentsPanelProps = {
  summary: RunSummary;
  dispatches: Dispatch[];
};

type AgentRow = {
  agent_name: string;
  status: string;
  phase: string;
  task_name: string;
  summary: string;
  updated_at: string;
  parallel_count: number;
};

const STATUS_TONE: Record<string, { label: string; className: string }> = {
  active:    { label: "ACTIVE",    className: "agents-panel__row--active" },
  running:   { label: "RUNNING",   className: "agents-panel__row--active" },
  completed: { label: "COMPLETED", className: "agents-panel__row--done" },
  done:      { label: "DONE",      className: "agents-panel__row--done" },
  idle:      { label: "IDLE",      className: "agents-panel__row--idle" },
  failed:    { label: "FAILED",    className: "agents-panel__row--failed" },
  error:     { label: "ERROR",     className: "agents-panel__row--failed" },
};

export function AgentsPanel({ summary, dispatches }: AgentsPanelProps) {
  // Parallel count comes from two sources, in priority order:
  //  1) Running Dispatch rows for this agent (parallel_dispatch.sh path —
  //     precise, one row per parallel batch)
  //  2) Backend's summary.agents[].parallel_count, derived from the cases
  //     table's `assigned_agent` column (works for non-parallel-dispatch
  //     flows too, since any concurrent case work gets recorded there)
  //  3) Fallback: 1 for active/running agents with no other signal, 0 otherwise
  const parallelByDispatch = new Map<string, number>();
  for (const d of dispatches) {
    if (d.state !== "running") continue;
    parallelByDispatch.set(d.agent, (parallelByDispatch.get(d.agent) ?? 0) + 1);
  }

  const rows: AgentRow[] = summary.agents.map((a) => {
    const isRunning = a.status === "active" || a.status === "running";
    const fromDispatches = parallelByDispatch.get(a.agent_name) ?? 0;
    const fromBackend = a.parallel_count ?? 0;
    const parallel = fromDispatches > 0
      ? fromDispatches
      : fromBackend > 0
        ? fromBackend
        : isRunning ? 1 : 0;
    return {
      agent_name: a.agent_name,
      status: a.status,
      phase: a.phase,
      task_name: a.task_name,
      summary: a.summary,
      updated_at: a.updated_at,
      parallel_count: parallel,
    };
  });

  // Primary sort: active first, then non-idle, then idle. Secondary: by name.
  const sortKey = (s: string) =>
    s === "active" || s === "running" ? 0 :
    s === "failed" || s === "error"   ? 1 :
    s === "idle"                       ? 3 :
                                          2;
  rows.sort((a, b) => {
    const k = sortKey(a.status) - sortKey(b.status);
    return k !== 0 ? k : a.agent_name.localeCompare(b.agent_name);
  });

  const activeRows = rows.filter((r) => r.status === "active" || r.status === "running");
  const activeTotal = activeRows.reduce((sum, r) => sum + Math.max(r.parallel_count, 1), 0);

  return (
    <section className="dash-card agents-panel" data-testid="agents-panel">
      <header className="dash-card__head">
        <h3 className="dash-card__title">Agents</h3>
        <p className="dash-card__sub">
          {activeTotal} active · {summary.overview.available_agents} defined
        </p>
      </header>
      {rows.length === 0 ? (
        <p className="dash-card__empty">No agent activity recorded yet.</p>
      ) : (
        <ul className="agents-panel__list">
          {rows.map((row) => {
            const tone = STATUS_TONE[row.status] ?? {
              label: row.status.toUpperCase(),
              className: "agents-panel__row--idle",
            };
            return (
              <li
                key={row.agent_name}
                className={`agents-panel__row ${tone.className}`}
              >
                <span className="agents-panel__dot" aria-hidden />
                <span className="agents-panel__name">{row.agent_name}</span>
                {row.parallel_count > 1 && (
                  <span className="agents-panel__parallel">×{row.parallel_count}</span>
                )}
                <span className="agents-panel__phase">{row.phase || "—"}</span>
                <span className="agents-panel__state">{tone.label}</span>
                {row.summary && (
                  <span className="agents-panel__summary" title={row.summary}>
                    {row.summary}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
