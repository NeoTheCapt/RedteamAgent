import { useMemo, useState } from "react";
import type { Dispatch, RunSummary } from "../../lib/api";
import { formatDurationSince } from "../../lib/formatDuration";
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
  total_dispatches: number;
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

function dispatchStateClass(state: string): string {
  if (state === "running" || state === "active") return "agents-panel__dispatch--active";
  if (state === "done" || state === "completed") return "agents-panel__dispatch--done";
  if (state === "failed" || state === "error")   return "agents-panel__dispatch--failed";
  return "agents-panel__dispatch--idle";
}

export function AgentsPanel({ summary, dispatches }: AgentsPanelProps) {
  // Per-agent dispatch history. Sorted most recent first so the freshly
  // completed work is at the top when the row is expanded.
  const dispatchesByAgent = useMemo(() => {
    const m = new Map<string, Dispatch[]>();
    for (const d of dispatches) {
      const list = m.get(d.agent) ?? [];
      list.push(d);
      m.set(d.agent, list);
    }
    for (const list of m.values()) {
      list.sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0));
    }
    return m;
  }, [dispatches]);

  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

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
      total_dispatches: dispatchesByAgent.get(a.agent_name)?.length ?? 0,
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

  // Cross-kind concurrency: distinct agents currently active. Surfaces the
  // streaming-pipeline design intent (recon+source / vuln+source / osint+exploit)
  // which the per-agent rows alone hide. Only render when 2+ distinct agents
  // are active — a single active agent is just sequential dispatch.
  const concurrentAgentNames = activeRows.map((r) => r.agent_name).sort();
  const showLiveConcurrency = concurrentAgentNames.length >= 2;

  // Historical concurrency: bucket Dispatch.started_at into 5s windows; keep
  // windows where 2+ distinct agents fired. Forward-looking — populated by the
  // dispatcher.sh / fetch_batch_to_file.sh emit hooks (5c46451). Old runs whose
  // engagement workspace was provisioned before that commit will show empty.
  const concurrencyWindows = useMemo(() => {
    const WINDOW_SEC = 5;
    const buckets = new Map<number, Set<string>>();
    for (const d of dispatches) {
      if (typeof d.started_at !== "number") continue;
      const bucket = Math.floor(d.started_at / WINDOW_SEC) * WINDOW_SEC;
      const set = buckets.get(bucket) ?? new Set<string>();
      set.add(d.agent);
      buckets.set(bucket, set);
    }
    return Array.from(buckets.entries())
      .filter(([, set]) => set.size >= 2)
      .sort(([a], [b]) => b - a)
      .slice(0, 6)
      .map(([ts, set]) => ({
        timestamp: new Date(ts * 1000).toLocaleTimeString(),
        agents: Array.from(set).sort(),
      }));
  }, [dispatches]);

  return (
    <section className="dash-card agents-panel" data-testid="agents-panel">
      <header className="dash-card__head">
        <h3 className="dash-card__title">Agents</h3>
        <p className="dash-card__sub">
          {activeTotal} active · {summary.overview.available_agents} defined
        </p>
      </header>
      {showLiveConcurrency && (
        <div className="agents-panel__concurrency-live" data-testid="agents-panel-concurrency-live">
          <span className="agents-panel__concurrency-label">Concurrent now</span>
          {concurrentAgentNames.map((name) => (
            <span key={name} className="agents-panel__concurrency-chip">{name}</span>
          ))}
        </div>
      )}
      {rows.length === 0 ? (
        <p className="dash-card__empty">No agent activity recorded yet.</p>
      ) : (
        <ul className="agents-panel__list">
          {rows.map((row) => {
            const tone = STATUS_TONE[row.status] ?? {
              label: row.status.toUpperCase(),
              className: "agents-panel__row--idle",
            };
            const expandable = row.total_dispatches > 0;
            const isExpanded = expandable && expandedAgent === row.agent_name;
            const agentDispatches = isExpanded
              ? (dispatchesByAgent.get(row.agent_name) ?? [])
              : [];
            return (
              <li key={row.agent_name} className="agents-panel__row-wrap">
                <button
                  type="button"
                  className={`agents-panel__row ${tone.className} ${expandable ? "agents-panel__row--clickable" : ""}`}
                  onClick={() => {
                    if (!expandable) return;
                    setExpandedAgent(isExpanded ? null : row.agent_name);
                  }}
                  aria-expanded={isExpanded}
                  aria-disabled={!expandable}
                  disabled={!expandable}
                  data-testid="agents-panel-row"
                >
                  <span className="agents-panel__chevron" aria-hidden>
                    {expandable ? (isExpanded ? "▾" : "▸") : ""}
                  </span>
                  <span className="agents-panel__dot" aria-hidden />
                  <span className="agents-panel__name">{row.agent_name}</span>
                  {row.parallel_count > 1 && (
                    <span className="agents-panel__parallel">×{row.parallel_count}</span>
                  )}
                  {row.total_dispatches > 0 && (
                    <span className="agents-panel__total" title={`${row.total_dispatches} total dispatch${row.total_dispatches === 1 ? "" : "es"} over the run`}>
                      {row.total_dispatches} total
                    </span>
                  )}
                  <span className="agents-panel__phase">{row.phase || "—"}</span>
                  <span className="agents-panel__state">{tone.label}</span>
                  {row.summary && (
                    <span className="agents-panel__summary" title={row.summary}>
                      {row.summary}
                    </span>
                  )}
                </button>
                {isExpanded && (
                  <ul className="agents-panel__dispatches" data-testid="agents-panel-dispatches">
                    {agentDispatches.map((d) => {
                      const duration = formatDurationSince(d.started_at, d.finished_at);
                      return (
                        <li
                          key={d.id}
                          className={`agents-panel__dispatch ${dispatchStateClass(d.state)}`}
                          data-testid="agents-panel-dispatch"
                        >
                          <span className="agents-panel__dispatch-phase">{d.phase}</span>
                          <span className="agents-panel__dispatch-slot">:{d.slot}</span>
                          <span className="agents-panel__dispatch-state">{d.state.toUpperCase()}</span>
                          {duration && (
                            <span className="agents-panel__dispatch-duration">{duration}</span>
                          )}
                          {d.task && (
                            <span className="agents-panel__dispatch-task" title={d.task}>
                              {d.task}
                            </span>
                          )}
                          {d.error && (
                            <span className="agents-panel__dispatch-error" title={d.error}>
                              error
                            </span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {concurrencyWindows.length > 0 && (
        <div className="agents-panel__concurrency-history" data-testid="agents-panel-concurrency-history">
          <h4 className="agents-panel__concurrency-title">Recent concurrent windows</h4>
          <ul className="agents-panel__concurrency-list">
            {concurrencyWindows.map((w) => (
              <li key={w.timestamp} className="agents-panel__concurrency-row">
                <span className="agents-panel__concurrency-time">{w.timestamp}</span>
                <span className="agents-panel__concurrency-agents">
                  {w.agents.map((a) => (
                    <span key={a} className="agents-panel__concurrency-chip">{a}</span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
