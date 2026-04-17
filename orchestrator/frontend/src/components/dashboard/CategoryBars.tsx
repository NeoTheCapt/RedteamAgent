import type { RunSummary } from "../../lib/api";

type CategoryBarsProps = {
  summary: RunSummary;
};

export function CategoryBars({ summary }: CategoryBarsProps) {
  const rows = summary.coverage.case_types
    .filter((t) => (t.done ?? 0) > 0 || (t.error ?? 0) > 0)
    .map((t) => ({
      name: t.type,
      done: t.done ?? 0,
      total: t.total ?? 0,
    }))
    .sort((a, b) => b.done - a.done);

  const max = Math.max(1, ...rows.map((r) => r.done));

  return (
    <div className="dash-card">
      <header className="dash-card__head">
        <h3 className="dash-card__title">Cases by Type</h3>
      </header>
      <div className="dash-card__body">
        {rows.length === 0 && (
          <p className="dash-card__empty">No cases processed yet.</p>
        )}
        <div className="cat-bars">
          {rows.map((r) => (
            <div key={r.name} className="cat-bar">
              <div className="cat-bar__name">{r.name}</div>
              <div className="cat-bar__track">
                <div
                  className="cat-bar__fill"
                  style={{ width: `${Math.max(5, (r.done / max) * 100)}%` }}
                >
                  {r.done} / {r.total}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
