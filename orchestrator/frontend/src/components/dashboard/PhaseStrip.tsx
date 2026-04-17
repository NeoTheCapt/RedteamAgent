import type { RunSummary } from "../../lib/api";

type PhaseStripProps = {
  summary: RunSummary;
};

const CANONICAL_PHASES = ["recon", "collect", "consume", "exploit", "report"] as const;
type PhaseName = (typeof CANONICAL_PHASES)[number];

function matchCanonical(raw: string): PhaseName | null {
  const s = (raw ?? "").toLowerCase().replace(/[-_]/g, "");
  if (s.includes("recon")) return "recon";
  if (s.includes("collect")) return "collect";
  if (s.includes("consume")) return "consume";
  if (s.includes("exploit")) return "exploit";
  if (s.includes("report")) return "report";
  return null;
}

export function PhaseStrip({ summary }: PhaseStripProps) {
  const current = matchCanonical(summary.overview.current_phase);
  const completedSet = new Set<PhaseName>();
  for (const ph of summary.phases) {
    if (ph.state === "completed") {
      const n = matchCanonical(ph.phase);
      if (n) completedSet.add(n);
    }
  }

  function stateOf(name: PhaseName): "done" | "active" | "pending" {
    if (completedSet.has(name)) return "done";
    if (current === name) return "active";
    return "pending";
  }

  return (
    <div className="phase-strip">
      {CANONICAL_PHASES.map((name, idx) => {
        const st = stateOf(name);
        return (
          <div key={name} className={`phase-strip__step phase-strip__step--${st}`}>
            <span className="phase-strip__ring">
              {st === "done" ? "✓" : st === "active" ? "●" : "○"}
            </span>
            <div className="phase-strip__text">
              <div className="phase-strip__name">{name.toUpperCase()}</div>
            </div>
            {idx < CANONICAL_PHASES.length - 1 && (
              <span className={`phase-strip__line ${st === "done" ? "phase-strip__line--done" : ""}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
