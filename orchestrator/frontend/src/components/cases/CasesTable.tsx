import type { Case } from "../../lib/api";

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
      <table className="cases-table">
        <thead>
          <tr>
            <th className="cases-table__col-state" scope="col">State</th>
            <th className="cases-table__col-id" scope="col">#</th>
            <th className="cases-table__col-method" scope="col">Method</th>
            <th className="cases-table__col-path" scope="col">Path</th>
            <th className="cases-table__col-cat" scope="col">Category</th>
            <th className="cases-table__col-result" scope="col">Result</th>
            <th className="cases-table__col-finding" scope="col">Finding</th>
            <th className="cases-table__col-dur" scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {cases.length === 0 && (
            <tr>
              <td colSpan={8} className="cases-table__empty">no cases match the current filters</td>
            </tr>
          )}
          {cases.map((c) => {
            const selected = c.case_id === selectedId;
            return (
              <tr
                key={c.case_id}
                className={`cases-table__row cases-table__row--${c.state} ${selected ? "cases-table__row--selected" : ""}`}
                onClick={() => onSelect(c.case_id)}
                aria-selected={selected}
              >
                <td className="cases-table__cell-state"><span className="cases-table__glyph" aria-hidden>{stateGlyph(c.state)}</span>{c.state}</td>
                <td className="cases-table__cell-id">{c.case_id}</td>
                <td className="cases-table__cell-method">{c.method}</td>
                <td className="cases-table__cell-path">{c.path}</td>
                <td className="cases-table__cell-cat">{c.category ?? "—"}</td>
                <td className="cases-table__cell-result">{c.result ?? "—"}</td>
                <td className="cases-table__cell-finding">{c.finding_id ?? "—"}</td>
                <td className="cases-table__cell-dur">{c.duration_ms !== null ? `${c.duration_ms}ms` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
