import type { RunSummary } from "../../lib/api";

type DashboardTabProps = {
  summary: RunSummary;
};

// Stub — full implementation in Tasks D1–D4.
export function DashboardTab({ summary }: DashboardTabProps) {
  return (
    <div style={{ color: "var(--c-text-muted)" }}>
      Dashboard — {summary.cases.total} cases, {summary.dispatches.total} dispatches
    </div>
  );
}
