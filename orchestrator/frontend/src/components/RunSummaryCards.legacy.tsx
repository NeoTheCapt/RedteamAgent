import type { RunSummary } from "../lib/api";

type RunSummaryCardsProps = {
  summary: RunSummary | null;
};

function titleCasePhase(phase: string) {
  if (phase === "consume-test") return "Consume & Test";
  if (!phase || phase === "unknown") return "Initializing";
  return phase
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function RunSummaryCards({ summary }: RunSummaryCardsProps) {
  const cards = [
    {
      label: "Target",
      value: summary?.target.hostname ?? "Waiting",
      detail: summary ? `${summary.target.scheme}://${summary.target.hostname}:${summary.target.port}` : "Waiting for target",
    },
    {
      label: "Phase",
      value: titleCasePhase(summary?.overview.current_phase ?? "unknown"),
      detail: summary?.current.summary ?? "No active task yet",
    },
    {
      label: "Active agents",
      value: String(summary?.overview.active_agents ?? 0),
      detail: summary ? `${summary.overview.available_agents} observed total` : "No agent activity yet",
    },
    {
      label: "Findings",
      value: String(summary?.overview.findings_count ?? 0),
      detail: summary ? `${summary.coverage.total_surfaces} tracked surfaces` : "Waiting for coverage data",
    },
    {
      label: "Path coverage",
      value: String(summary?.coverage.completed_cases ?? 0),
      detail: summary ? `${summary.coverage.total_cases} total case paths` : "Waiting for cases.db",
    },
    {
      label: "Remaining work",
      value: String((summary?.coverage.pending_cases ?? 0) + (summary?.coverage.processing_cases ?? 0)),
      detail: summary
        ? `${summary.coverage.remaining_surfaces} surfaces, ${summary.coverage.high_risk_remaining} high risk`
        : "Waiting for surface data",
    },
    {
      label: "Runtime model",
      value: summary?.runtime_model.observed_model || summary?.runtime_model.configured_model || "Waiting",
      detail: summary
        ? `${summary.runtime_model.status}: ${summary.runtime_model.observed_provider || summary.runtime_model.configured_provider || "provider unset"}`
        : "Waiting for runtime metadata",
    },
  ];

  return (
    <section className="summary-card-grid">
      {cards.map((card) => (
        <article key={card.label} className="panel summary-card">
          <p className="eyebrow">{card.label}</p>
          <strong className="summary-value">{card.value}</strong>
          <p className="summary-detail">{card.detail}</p>
        </article>
      ))}
    </section>
  );
}
