import type { Case, Dispatch } from "../../lib/api";
import { DispatchCard } from "./DispatchCard";

type KanbanColumnProps = {
  phase: string;
  label: string;
  state: "done" | "active" | "pending";
  dispatches: Dispatch[];
  casesByDispatchId: Map<string | null, Case[]>;
};

export function KanbanColumn({
  phase, label, state, dispatches, casesByDispatchId,
}: KanbanColumnProps) {
  const stateClass = `kanban-col--${state}`;
  const runningCount = dispatches.filter((d) => d.state === "running").length;

  return (
    <section className={`kanban-col ${stateClass}`} data-phase={phase}>
      <header className="kanban-col__head">
        <span className="kanban-col__name">{label}</span>
        <span className="kanban-col__badge">{runningCount > 0 ? `${runningCount} running` : state}</span>
      </header>
      <div className="kanban-col__stack">
        {dispatches.length === 0 && (
          <p className="kanban-col__empty">no dispatches</p>
        )}
        {dispatches.map((d) => (
          <DispatchCard
            key={d.id}
            dispatch={d}
            cases={casesByDispatchId.get(d.id) ?? []}
          />
        ))}
      </div>
    </section>
  );
}
