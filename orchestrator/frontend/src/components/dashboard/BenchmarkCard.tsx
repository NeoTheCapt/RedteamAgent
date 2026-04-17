import type { RunSummary } from "../../lib/api";

type BenchmarkCardProps = {
  summary: RunSummary;
};

// Reads from summary.benchmark_json (extended runs column added in Plan 1 Task A4)
// when populated; otherwise shows an empty state.
export function BenchmarkCard({ summary }: BenchmarkCardProps) {
  // The summary endpoint doesn't yet surface benchmark_json;
  // render a placeholder until it does. The `summary` prop is kept for future use.
  void summary;
  const hasBenchmark = false;

  return (
    <div className="dash-card">
      <header className="dash-card__head">
        <h3 className="dash-card__title">Benchmark</h3>
        <p className="dash-card__sub">target-specific scoring</p>
      </header>
      <div className="dash-card__body">
        {!hasBenchmark && (
          <p className="dash-card__empty">
            No benchmark configured. Juice-shop recall exposed in a follow-up plan.
          </p>
        )}
      </div>
    </div>
  );
}
