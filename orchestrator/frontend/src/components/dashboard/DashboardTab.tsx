import { useMemo, useState } from "react";
import type { RunSummary, Dispatch } from "../../lib/api";
import { listDispatches } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { summarizeAgentParticipation } from "../../lib/agentParticipation";
import { KpiRow } from "./KpiRow";
import { PhaseStrip } from "./PhaseStrip";
import { SeverityDonut } from "./SeverityDonut";
import { CategoryBars } from "./CategoryBars";
import "./dashboard.css";

type DashboardTabProps = {
  token: string;
  projectId: number;
  runId: number;
  summary: RunSummary;
};

export function DashboardTab({ token, projectId, runId, summary }: DashboardTabProps) {
  const [dispatches, setDispatches] = useState<Dispatch[]>([]);

  useAutoRefresh(
    async (signal) => {
      const rows = await listDispatches(token, projectId, runId);
      if (!signal.aborted) setDispatches(rows);
    },
    [token, projectId, runId],
  );

  const participation = useMemo(
    () => summarizeAgentParticipation(summary, dispatches),
    [summary, dispatches],
  );

  return (
    <div className="dashboard">
      <KpiRow summary={summary} participation={participation} />
      <PhaseStrip summary={summary} />
      <div className="dashboard__grid">
        <CategoryBars summary={summary} />
        <div className="dashboard__col">
          <SeverityDonut summary={summary} />
        </div>
      </div>
    </div>
  );
}
