import type { Dispatch, RunSummary } from "./api";

export type AgentParticipation = {
  activeTotal: number;
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
  const counts = new Map<string, number>();

  for (const dispatch of dispatches) {
    if (dispatch.state !== "running") continue;
    counts.set(dispatch.agent, (counts.get(dispatch.agent) ?? 0) + 1);
  }

  if (counts.size === 0) {
    for (const agent of summary.agents) {
      if (agent.status !== "active") continue;
      counts.set(agent.agent_name, (counts.get(agent.agent_name) ?? 0) + 1);
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
