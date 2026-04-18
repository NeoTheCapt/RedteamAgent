import { useState, useMemo } from "react";
import type { Case, Dispatch } from "../../lib/api";
import { listDispatches, listCases } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { KanbanColumn } from "./KanbanColumn";
import "./progress.css";

type ProgressTabProps = {
  token: string;
  projectId: number;
  runId: number;
  currentPhase: string | null;
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

export function ProgressTab({ token, projectId, runId, currentPhase }: ProgressTabProps) {
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

  return (
    <div className="progress" data-testid="progress-tab">
      {error && (
        <div className="progress__error" role="alert">
          Failed to load progress: {error}
        </div>
      )}
      {CANONICAL_PHASES.map(({ phase, label }) => {
        const dispatches = dispatchesByPhase.get(phase) ?? [];
        const colState = columnState(phase, currentPhase, dispatches);
        const unassigned = colState === "active"
          ? (casesByDispatch.get(null) ?? [])
          : [];
        return (
          <KanbanColumn
            key={phase}
            phase={phase}
            label={label}
            state={colState}
            dispatches={dispatches}
            casesByDispatchId={casesByDispatch}
            unassignedCases={unassigned}
          />
        );
      })}
    </div>
  );
}
