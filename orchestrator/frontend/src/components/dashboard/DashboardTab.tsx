import type { RunSummary } from "../../lib/api";
import { KpiRow } from "./KpiRow";
import { PhaseStrip } from "./PhaseStrip";
import { SeverityDonut } from "./SeverityDonut";
import { CategoryBars } from "./CategoryBars";
import { BenchmarkCard } from "./BenchmarkCard";
import "./dashboard.css";

type DashboardTabProps = {
  summary: RunSummary;
};

export function DashboardTab({ summary }: DashboardTabProps) {
  return (
    <div className="dashboard">
      <KpiRow summary={summary} />
      <PhaseStrip summary={summary} />
      <div className="dashboard__grid">
        <CategoryBars summary={summary} />
        <div className="dashboard__col">
          <SeverityDonut summary={summary} />
          <BenchmarkCard summary={summary} />
        </div>
      </div>
    </div>
  );
}
