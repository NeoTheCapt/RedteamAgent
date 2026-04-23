import { useState } from "react";
import type { ReactNode } from "react";
import type { Run } from "../../lib/api";

type RunPanelProps = {
  run: Run;
  runtimeLabel?: string;
  currentPhase?: string | null;
  onStop?: () => void | Promise<void>;
  children: ReactNode;
};

function ribbonState(run: Run): "done" | "failed" | "stopped" | "active" {
  const s = run.status.toLowerCase();
  if (s === "completed") return "done";
  if (s === "failed" || s === "error") return "failed";
  if (s === "stopped") return "stopped";
  return "active";
}

function badgeLabel(run: Run, currentPhase?: string | null): string | null {
  if (currentPhase && ribbonState(run) === "active") {
    return currentPhase.toUpperCase();
  }
  const normalizedStatus = run.status.replace(/_/g, "-").toUpperCase();
  return normalizedStatus || null;
}

export function RunPanel({ run, runtimeLabel, currentPhase, onStop, children }: RunPanelProps) {
  const state = ribbonState(run);
  const isRunning = state === "active";
  const label = badgeLabel(run, currentPhase);
  const [stopping, setStopping] = useState(false);

  async function handleStopClick() {
    if (stopping || !onStop) return;
    setStopping(true);
    try { await onStop(); } finally { setStopping(false); }
  }

  return (
    <section
      className={`run-panel ${state === "done" ? "run-panel--done" : ""} ${state === "failed" ? "run-panel--failed" : ""} ${state === "stopped" ? "run-panel--stopped" : ""}`}
      aria-label={`Run ${run.target}`}
    >
      <header className="run-panel__ctx">
        <div className="run-panel__ctx-left">
          {isRunning && <span className="run-panel__dot" aria-label="running" />}
          <span className="run-panel__target">{run.target}</span>
          <span className="run-panel__id">#r-{run.id}</span>
          {label && (
            <span className={`run-panel__badge run-panel__badge--${state}`}>{label}</span>
          )}
        </div>
        <div className="run-panel__ctx-right">
          {runtimeLabel && <span className="run-panel__time">{runtimeLabel}</span>}
          {isRunning && onStop && (
            <button type="button" className="run-panel__stop" onClick={() => void handleStopClick()} disabled={stopping}>
              {stopping ? "Stopping…" : "◼ STOP"}
            </button>
          )}
        </div>
      </header>
      {children}
    </section>
  );
}
