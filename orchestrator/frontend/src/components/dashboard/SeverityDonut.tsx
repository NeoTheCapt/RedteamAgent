import type { RunSummary } from "../../lib/api";

type SeverityDonutProps = {
  summary: RunSummary;
};

// Placeholder: the backend summary doesn't yet expose per-severity finding counts.
// The component reads from a future `summary.severity_breakdown` once exposed.
// Until then, it renders an empty state showing the total findings count.
export function SeverityDonut({ summary }: SeverityDonutProps) {
  const total = summary.overview.findings_count;
  return (
    <div className="dash-card">
      <header className="dash-card__head">
        <h3 className="dash-card__title">Severity</h3>
      </header>
      <div className="dash-card__body dash-card__body--centered">
        <svg viewBox="0 0 42 42" width="140" height="140" aria-label="Severity breakdown">
          <circle cx="21" cy="21" r="15.9" fill="var(--c-panel-soft)" />
          <text x="21" y="22" textAnchor="middle" fill="var(--c-text)"
                fontSize="7" fontWeight="700" fontFamily="var(--font-mono)">
            {total}
          </text>
          <text x="21" y="27" textAnchor="middle" fill="var(--c-text-dim)"
                fontSize="2.5" fontFamily="var(--font-mono)">
            TOTAL
          </text>
        </svg>
        <p className="dash-card__empty">
          Per-severity breakdown arrives when the summary endpoint exposes it.
        </p>
      </div>
    </div>
  );
}
