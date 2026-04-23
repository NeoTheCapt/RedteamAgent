import { useState, useMemo } from "react";
import type { Case, Dispatch, RunSummary } from "../../lib/api";
import { listDispatches, listCases } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { summarizeAgentParticipation } from "../../lib/agentParticipation";
import { KanbanColumn } from "./KanbanColumn";
import "./progress.css";

type ProgressTabProps = {
  token: string;
  projectId: number;
  runId: number;
  currentPhase: string | null;
  summary: RunSummary;
};

const CANONICAL_PHASES: { phase: string; label: string; match: (p: string) => boolean }[] = [
  { phase: "recon",    label: "Recon",        match: (p) => /^recon(?:$|[-_])/i.test(p) },
  { phase: "collect",  label: "Collect",      match: (p) => /^collect(?:$|[-_])/i.test(p) },
  { phase: "consume",  label: "Consume-Test", match: (p) => /^consume(?:$|[-_])/i.test(p) },
  { phase: "exploit",  label: "Exploit",      match: (p) => /^exploit(?:$|[-_])/i.test(p) },
  { phase: "report",   label: "Report",       match: (p) => /^report(?:$|[-_])/i.test(p) },
];

function normalizePhase(raw: string): string {
  for (const p of CANONICAL_PHASES) if (p.match(raw)) return p.phase;
  return raw || "consume";
}

function columnState(
  phase: string,
  currentPhase: string | null,
  dispatches: Dispatch[],
): "done" | "active" | "pending" {
  const normalizedCurrent = currentPhase ? normalizePhase(currentPhase) : null;
  const order = CANONICAL_PHASES.map((p) => p.phase);
  const curIdx = normalizedCurrent ? order.indexOf(normalizedCurrent) : -1;
  const myIdx = order.indexOf(phase);
  if (curIdx < 0) {
    const anyRunning = dispatches.some((d) => d.state === "running");
    if (anyRunning) return "active";
    if (dispatches.length > 0) return "done";
    return "pending";
  }
  if (myIdx < curIdx) return "done";
  if (myIdx === curIdx) return "active";
  return "pending";
}

function phaseSummaryLines(phase: string, summary: RunSummary): string[] {
  const phaseCard = summary.phases.find((item) => normalizePhase(item.phase) === phase);
  const latestSummary = phaseCard?.latest_summary?.trim();
  switch (phase) {
    case "recon": {
      const scopeCount = summary.target.scope_entries.length;
      return [
        `Target ${summary.target.target}`,
        scopeCount > 0 ? `${scopeCount} scope entr${scopeCount === 1 ? "y" : "ies"}` : "Scope inherited from target URL",
        latestSummary || `${summary.coverage.total_cases} requestable paths queued from recon artifacts`,
      ];
    }
    case "collect":
      return [
        `${summary.coverage.total_surfaces} surface candidates recorded`,
        `${summary.coverage.high_risk_remaining} high-risk surfaces still unresolved`,
        latestSummary || `${summary.coverage.total_cases} queued URLs/cases observed during collection`,
      ];
    case "consume":
      return [
        `${summary.cases.done + summary.cases.findings} / ${summary.cases.total} cases processed`,
        `${summary.cases.queued} queued · ${summary.cases.running} running · ${summary.cases.findings} findings`,
        latestSummary || `${summary.dispatches.active} active dispatches · ${summary.dispatches.done} completed`,
      ];
    case "exploit":
      return [
        `${summary.overview.findings_count} findings recorded`,
        `${phaseCard?.active_agents ?? 0} active exploit agents`,
        latestSummary || (summary.overview.findings_count > 0 ? "Review findings.md for in-flight exploit follow-ups" : "Awaiting confirmed findings before exploitation"),
      ];
    case "report":
      return [
        `Report path ${summary.target.engagement_dir}/report.md`,
        latestSummary || (phaseCard?.state === "completed" ? "Final report generated" : "Final report pending after exploit completion"),
      ];
    default:
      return latestSummary ? [latestSummary] : [];
  }
}

export function ProgressTab({ token, projectId, runId, currentPhase, summary }: ProgressTabProps) {
  const [dispatches, setDispatches] = useState<Dispatch[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [error, setError] = useState<string | null>(null);

  useAutoRefresh(
    async (signal) => {
      try {
        const [ds, cs] = await Promise.all([
          listDispatches(token, projectId, runId),
          listCases(token, projectId, runId),
        ]);
        if (signal.aborted) return;
        setDispatches(ds);
        setCases(cs);
        setError(null);
      } catch (err) {
        if (signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [token, projectId, runId],
  );

  const casesByDispatch = useMemo(() => {
    const m = new Map<string | null, Case[]>();
    for (const c of cases) {
      const key = c.dispatch_id;
      const list = m.get(key) ?? [];
      list.push(c);
      m.set(key, list);
    }
    return m;
  }, [cases]);

  const dispatchesByPhase = useMemo(() => {
    const m = new Map<string, Dispatch[]>();
    for (const d of dispatches) {
      const phase = normalizePhase(d.phase);
      const list = m.get(phase) ?? [];
      list.push(d);
      m.set(phase, list);
    }
    for (const list of m.values()) {
      list.sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0));
    }
    return m;
  }, [dispatches]);

  const participation = useMemo(
    () => summarizeAgentParticipation(summary, dispatches),
    [summary, dispatches],
  );

  return (
    <div className="progress-wrap" data-testid="progress-tab">
      {error && (
        <div className="progress__error" role="alert">
          Failed to load progress: {error}
        </div>
      )}
      <div className="progress__meta" aria-label="Agent participation summary">
        <div className="progress__meta-label">Agent participation</div>
        <div className="progress__meta-value">{participation.activeTotal} agents active</div>
        <div className="progress__meta-sub">
          {participation.text} · full breakdown on the <strong>Dashboard</strong> tab
        </div>
      </div>
      <div className="progress">
        {CANONICAL_PHASES.map(({ phase, label }) => {
          const phaseDispatches = dispatchesByPhase.get(phase) ?? [];
          const colState = columnState(phase, currentPhase, phaseDispatches);
          const unassigned = colState === "active"
            ? (casesByDispatch.get(null) ?? [])
            : [];
          return (
            <KanbanColumn
              key={phase}
              phase={phase}
              label={label}
              state={colState}
              dispatches={phaseDispatches}
              casesByDispatchId={casesByDispatch}
              summaryLines={phaseSummaryLines(phase, summary)}
              unassignedCases={unassigned}
            />
          );
        })}
      </div>
    </div>
  );
}
