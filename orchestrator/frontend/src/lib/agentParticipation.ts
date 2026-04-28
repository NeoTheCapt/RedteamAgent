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

function inferTrackedAgentCount(
  agent: { agent_name: string; status: string; parallel_count?: number | null },
  parallelByDispatch: Map<string, number>,
): number {
  const fromDispatches = parallelByDispatch.get(agent.agent_name) ?? 0;
  const fromBackend = agent.parallel_count ?? 0;
  const touchedRun = agent.status !== "idle" && agent.status !== "";
  const observedParallel = Math.max(fromDispatches, fromBackend);
  if (observedParallel > 0) return observedParallel;
  return touchedRun ? 1 : 0;
}

export function summarizeAgentParticipation(
  summary: Pick<RunSummary, "overview" | "agents">,
  dispatches: Dispatch[],
): AgentParticipation {
  // Unified source of tracked participation. Priority (matches AgentsPanel as
  // closely as possible):
  //   1. Live running Dispatch rows (parallel_dispatch.sh path)
  //   2. summary.agents[].parallel_count from cases.db assigned_agent
  //   3. Fallback: 1 for any non-idle agent so completed/failed runs still
  //      expose which agent types participated after active concurrency drops
  //      back to zero.
  // activeTotal still reflects live active concurrency; the breakdown text is
  // intentionally historical so Dashboard/Progress keep the per-type context.
  const counts = new Map<string, number>();

  for (const dispatch of dispatches) {
    if (dispatch.state !== "running") continue;
    counts.set(dispatch.agent, (counts.get(dispatch.agent) ?? 0) + 1);
  }

  for (const agent of summary.agents) {
    const count = inferTrackedAgentCount(agent, new Map());
    const existing = counts.get(agent.agent_name) ?? 0;
    if (count > existing) counts.set(agent.agent_name, count);
  }

  const breakdown = Array.from(counts.entries())
    .map(([agent_name, count]) => ({ agent_name, count }))
    .sort((a, b) => (b.count - a.count) || a.agent_name.localeCompare(b.agent_name));

  const activeTotal = summary.overview.active_agents;
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
    .map((agent) => ({
      agent_name: agent.agent_name,
      count: inferTrackedAgentCount(agent, parallelByDispatch),
    }))
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
