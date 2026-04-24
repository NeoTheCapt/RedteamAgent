import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Run } from "../../lib/api";

type RunPanelProps = {
  run: Run;
  runtimeLabel?: string;
  currentPhase?: string | null;
  stopRequestedAt?: number | null;
  onStop?: () => void | Promise<void>;
  children: ReactNode;
};

const STOPPING_RIBBON_MS = 10_000;

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

export function RunPanel({
  run,
  runtimeLabel,
  currentPhase,
  stopRequestedAt = null,
  onStop,
  children,
}: RunPanelProps) {
  const state = ribbonState(run);
  const [stopping, setStopping] = useState(false);
  const [localStopRequestedAt, setLocalStopRequestedAt] = useState<number | null>(null);
  const effectiveStopRequestedAt = stopRequestedAt ?? localStopRequestedAt;
  const stopTransitioning = effectiveStopRequestedAt !== null;
  const visualState = stopTransitioning ? "stopped" : state;
  const isRunning = state === "active" && !stopTransitioning;
  const label = stopTransitioning ? "STOPPING" : badgeLabel(run, currentPhase);

  useEffect(() => {
    if (localStopRequestedAt === null) return;
    const remaining = Math.max(0, STOPPING_RIBBON_MS - (Date.now() - localStopRequestedAt));
    const timer = window.setTimeout(() => setLocalStopRequestedAt(null), remaining);
    return () => window.clearTimeout(timer);
  }, [localStopRequestedAt]);

  async function handleStopClick() {
    if (stopping || !onStop) return;
    setStopping(true);
    setLocalStopRequestedAt(Date.now());
    try {
      await onStop();
    } finally {
      setStopping(false);
    }
  }

  return (
    <section
      className={`run-panel ${visualState === "done" ? "run-panel--done" : ""} ${visualState === "failed" ? "run-panel--failed" : ""} ${visualState === "stopped" ? "run-panel--stopped" : ""}`}
      aria-label={`Run ${run.target}`}
    >
      <header className="run-panel__ctx">
        <div className="run-panel__ctx-left">
          {isRunning && <span className="run-panel__dot" aria-label="running" />}
          <span className="run-panel__target">{run.target}</span>
          <span className="run-panel__id">#r-{run.id}</span>
          {label && (
            <span className={`run-panel__badge run-panel__badge--${visualState}`}>{label}</span>
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
