import { useState } from "react";
import type { Case, Dispatch } from "../../lib/api";
import { DispatchCard } from "./DispatchCard";
import { CaseChip } from "./CaseChip";
import { PhaseSummary } from "./PhaseSummary";

type KanbanColumnProps = {
  phase: string;
  label: string;
  state: "done" | "active" | "pending";
  dispatches: Dispatch[];
  casesByDispatchId: Map<string | null, Case[]>;
  summaryLines?: string[];
  /**
   * Cases that belong in this column but aren't tied to any dispatch row
   * (dispatch_id = null). Rendered in a trailing "Unassigned" slot.
   * Only populated for the active phase — other phases pass []. */
  unassignedCases?: Case[];
};

export function KanbanColumn({
  phase, label, state, dispatches, casesByDispatchId, summaryLines = [], unassignedCases = [],
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
        <PhaseSummary lines={summaryLines} />
        {dispatches.length === 0 && unassignedCases.length === 0 && (
          <p className="kanban-col__empty">no dispatches</p>
        )}
        {dispatches.map((d) => (
          <DispatchCard
            key={d.id}
            dispatch={d}
            cases={casesByDispatchId.get(d.id) ?? []}
          />
        ))}
        {unassignedCases.length > 0 && (
          <UnassignedSlot cases={unassignedCases} />
        )}
      </div>
    </section>
  );
}

function UnassignedSlot({ cases }: { cases: Case[] }) {
  const [openCase, setOpenCase] = useState<number | null>(null);
  return (
    <article className="dispatch-card dispatch-card--unassigned">
      <header className="dispatch-card__head">
        <span className="dispatch-card__dot" aria-hidden />
        <span className="dispatch-card__agent">unassigned</span>
        <span className="dispatch-card__state">PENDING</span>
      </header>
      <div className="dispatch-card__task">
        Cases not yet linked to a dispatch (dispatch_start pending or dropped)
      </div>
      <div className="dispatch-card__chips">
        {cases.map((c) => (
          <CaseChip
            key={c.case_id}
            case_={c}
            expanded={openCase === c.case_id}
            onToggle={() =>
              setOpenCase((prev) => (prev === c.case_id ? null : c.case_id))
            }
          />
        ))}
      </div>
    </article>
  );
}
