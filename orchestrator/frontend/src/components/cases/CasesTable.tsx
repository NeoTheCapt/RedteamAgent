import type { Case } from "../../lib/api";
import { formatDuration } from "../../lib/formatDuration";

type CasesTableProps = {
  cases: Case[];
  selectedId: number | null;
  onSelect: (caseId: number) => void;
};

function stateGlyph(state: string): string {
  switch (state) {
    case "done":    return "✓";
    case "finding": return "⚠";
    case "running": return "▶";
    case "queued":  return "○";
    case "error":   return "!";
    default:        return "·";
  }
}

export function CasesTable({ cases, selectedId, onSelect }: CasesTableProps) {
  return (
    <div className="cases-table-wrap">
      <table className="cases-table" role="grid">
        <thead>
          <tr role="row">
            <th className="cases-table__col-state" role="columnheader" scope="col">State</th>
            <th className="cases-table__col-id" role="columnheader" scope="col">#</th>
            <th className="cases-table__col-method" role="columnheader" scope="col">Method</th>
            <th className="cases-table__col-path" role="columnheader" scope="col">Path</th>
            <th className="cases-table__col-cat" role="columnheader" scope="col">Category</th>
            <th className="cases-table__col-result" role="columnheader" scope="col">Result</th>
            <th className="cases-table__col-finding" role="columnheader" scope="col">Finding</th>
            <th className="cases-table__col-dur" role="columnheader" scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {cases.length === 0 && (
            <tr role="row">
              <td role="gridcell" colSpan={8} className="cases-table__empty">no cases match the current filters</td>
            </tr>
          )}
          {cases.map((c) => {
            const selected = c.case_id === selectedId;
            return (
              <tr
                key={c.case_id}
                role="row"
                className={`cases-table__row cases-table__row--${c.state} ${selected ? "cases-table__row--selected" : ""}`}
                onClick={() => onSelect(c.case_id)}
                tabIndex={0}
                aria-selected={selected}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(c.case_id);
                  }
                }}
              >
                <td role="gridcell" className="cases-table__cell-state"><span className="cases-table__glyph" aria-hidden>{stateGlyph(c.state)}</span>{c.state}</td>
                <td role="gridcell" className="cases-table__cell-id">{c.case_id}</td>
                <td role="gridcell" className="cases-table__cell-method">{c.method}</td>
                <td role="gridcell" className="cases-table__cell-path">{c.path}</td>
                <td role="gridcell" className="cases-table__cell-cat">{c.category ?? "—"}</td>
                <td role="gridcell" className="cases-table__cell-result">{c.result ?? "—"}</td>
                <td role="gridcell" className="cases-table__cell-finding">{c.finding_id ?? "—"}</td>
                <td role="gridcell" className="cases-table__cell-dur">{formatDuration(c.duration_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
