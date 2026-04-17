import { useState } from "react";
import type { Case, Dispatch } from "../../lib/api";
import { CaseChip } from "./CaseChip";

type DispatchCardProps = {
  dispatch: Dispatch;
  cases: Case[];
};

function durationLabel(d: Dispatch): string {
  if (d.started_at === null) return "";
  const end = d.finished_at ?? Math.floor(Date.now() / 1000);
  const secs = Math.max(0, end - d.started_at);
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs - m * 60;
  return `${m}m ${s}s`;
}

export function DispatchCard({ dispatch, cases }: DispatchCardProps) {
  const [openCase, setOpenCase] = useState<number | null>(null);
  const stateClass = `dispatch-card--${dispatch.state}`;
  const label = durationLabel(dispatch);

  return (
    <article className={`dispatch-card ${stateClass}`}>
      <header className="dispatch-card__head">
        <span className="dispatch-card__dot" aria-hidden />
        <span className="dispatch-card__agent">{dispatch.agent}</span>
        <span className="dispatch-card__slot">:s{dispatch.slot}</span>
        <span className="dispatch-card__state">{dispatch.state.toUpperCase()}</span>
        {label && <span className="dispatch-card__duration">{label}</span>}
      </header>
      {dispatch.task && (
        <div className="dispatch-card__task">{dispatch.task}</div>
      )}
      <div className="dispatch-card__chips">
        {cases.length === 0 && (
          <span className="dispatch-card__empty">no cases yet</span>
        )}
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
