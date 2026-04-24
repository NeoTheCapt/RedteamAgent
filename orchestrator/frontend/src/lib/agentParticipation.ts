import type { Dispatch, RunSummary } from "./api";

export type AgentParticipation = {
  activeTotal: number;
  breakdown: Array<{
    agent_name: string;
    count: number;
  }>;
  text: string;
};

export type AgentCoverageSummary = {
  trackedAgents: number;
  breakdown: Array<{
    agent_name: string;
    count: number;
  }>;
  text: string;
};

export function summarizeAgentParticipation(
  summary: Pick<RunSummary, "overview" | "agents">,
  dispatches: Dispatch[],
): AgentParticipation {
  // Unified source of agent concurrency counts. Priority (matches AgentsPanel):
  //   1. Live running Dispatch rows (parallel_dispatch.sh path)
  //   2. summary.agents[].parallel_count from cases.db assigned_agent
  //   3. Fallback: 1 per active agent from summary.agents
  // All three end up producing the same {agent_name: count} map, which is
  // also exactly what Dashboard's KpiRow "Active Agents" now sums. So the
  // number rendered as "Active Agents: N" and the sum of "×N" in the
  // breakdown stay in agreement across every surface.
  const counts = new Map<string, number>();

  for (const dispatch of dispatches) {
    if (dispatch.state !== "running") continue;
    counts.set(dispatch.agent, (counts.get(dispatch.agent) ?? 0) + 1);
  }

  if (counts.size === 0) {
    for (const agent of summary.agents) {
      if (agent.status !== "active" && agent.status !== "running") continue;
      const fromBackend = agent.parallel_count ?? 0;
      counts.set(agent.agent_name, fromBackend > 0 ? fromBackend : 1);
    }
  }

  const breakdown = Array.from(counts.entries())
    .map(([agent_name, count]) => ({ agent_name, count }))
    .sort((a, b) => (b.count - a.count) || a.agent_name.localeCompare(b.agent_name));

  const activeTotal = breakdown.reduce((sum, item) => sum + item.count, 0) || summary.overview.active_agents;
  const text = breakdown.length > 0
    ? breakdown.map((item) => `${item.count}× ${item.agent_name}`).join(", ")
    : "no active agents";

  return { activeTotal, breakdown, text };
}

export function summarizeTrackedAgentCoverage(
  summary: Pick<RunSummary, "agents">,
  dispatches: Dispatch[],
): AgentCoverageSummary {
  const parallelByDispatch = new Map<string, number>();
  for (const dispatch of dispatches) {
    if (dispatch.state !== "running") continue;
    parallelByDispatch.set(dispatch.agent, (parallelByDispatch.get(dispatch.agent) ?? 0) + 1);
  }

  const breakdown = summary.agents
    .map((agent) => {
      const isRunning = agent.status === "active" || agent.status === "running";
      const fromDispatches = parallelByDispatch.get(agent.agent_name) ?? 0;
      const fromBackend = agent.parallel_count ?? 0;
      const count = fromDispatches > 0
        ? fromDispatches
        : fromBackend > 0
          ? fromBackend
          : isRunning
            ? 1
            : 0;
      return {
        agent_name: agent.agent_name,
        count,
      };
    })
    .filter((item) => item.count > 0)
    .sort((a, b) => (b.count - a.count) || a.agent_name.localeCompare(b.agent_name));

  return {
    trackedAgents: breakdown.length,
    breakdown,
    text: breakdown.length > 0
      ? breakdown.map((item) => `${item.count}× ${item.agent_name}`).join(", ")
      : "no agent participation recorded",
  };
}
