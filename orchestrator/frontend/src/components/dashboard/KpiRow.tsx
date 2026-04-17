import type { RunSummary } from "../../lib/api";

type KpiRowProps = {
  summary: RunSummary;
};

export function KpiRow({ summary }: KpiRowProps) {
  const findings = summary.overview.findings_count;
  const casesDone = summary.cases.done + summary.cases.findings;
  const casesTotal = summary.cases.total;
  const dispatchesTotal = summary.dispatches.total;
  const dispatchesActive = summary.dispatches.active;
  const errors = summary.cases.error;

  return (
    <div className="kpi-row">
      <Kpi label="Findings" value={findings} tone="red" />
      <Kpi
        label="Cases Tested"
        value={`${casesDone} / ${casesTotal}`}
        sub={casesTotal > 0 ? `${Math.round((casesDone / casesTotal) * 100)}% coverage` : "—"}
      />
      <Kpi
        label="Dispatched"
        value={dispatchesTotal}
        tone="green"
        sub={`${dispatchesActive} active · ${summary.dispatches.done} done`}
      />
      <Kpi
        label="Errors"
        value={errors}
        tone={errors > 0 ? "amber" : "default"}
      />
      <Kpi
        label="Active Agents"
        value={summary.overview.active_agents}
        sub={`of ${summary.overview.available_agents}`}
      />
    </div>
  );
}

function Kpi({
  label, value, sub, tone = "default",
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone?: "default" | "red" | "green" | "amber";
}) {
  return (
    <div className={`kpi kpi--${tone}`}>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">{value}</div>
      {sub && <div className="kpi__sub">{sub}</div>}
    </div>
  );
}
