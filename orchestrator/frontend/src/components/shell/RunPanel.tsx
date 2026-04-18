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

function ribbonState(run: Run): "done" | "failed" | "active" {
  const s = run.status.toLowerCase();
  if (s === "completed") return "done";
  if (s === "failed" || s === "error") return "failed";
  return "active";
}

export function RunPanel({ run, runtimeLabel, currentPhase, onStop, children }: RunPanelProps) {
  const state = ribbonState(run);
  const isRunning = state === "active";
  const [stopping, setStopping] = useState(false);

  async function handleStopClick() {
    if (stopping || !onStop) return;
    setStopping(true);
    try { await onStop(); } finally { setStopping(false); }
  }

  return (
    <section
      className={`run-panel ${state === "done" ? "run-panel--done" : ""} ${state === "failed" ? "run-panel--failed" : ""}`}
      aria-label={`Run ${run.target}`}
    >
      <header className="run-panel__ctx">
        <div className="run-panel__ctx-left">
          {isRunning && <span className="run-panel__dot" aria-label="running" />}
          <span className="run-panel__target">{run.target}</span>
          <span className="run-panel__id">#r-{run.id}</span>
          {currentPhase && (
            <span className="run-panel__badge">{currentPhase.toUpperCase()}</span>
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
