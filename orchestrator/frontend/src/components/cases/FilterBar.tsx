import type { CaseListFilter } from "../../lib/api";

export type FilterValues = Required<CaseListFilter> & { q: string };

type FilterBarProps = {
  value: FilterValues;
  onChange: (next: FilterValues) => void;
  resultCount: number;
  totalCount: number;
};

const STATES = ["", "done", "running", "queued", "finding", "error"] as const;
const METHODS = ["", "GET", "POST", "PUT", "DELETE", "PATCH"] as const;

export function FilterBar({ value, onChange, resultCount, totalCount }: FilterBarProps) {
  return (
    <div className="filter-bar" role="group" aria-label="Case filters">
      <label className="filter-bar__field">
        <span className="filter-bar__label">State</span>
        <select
          className="filter-bar__input"
          value={value.state}
          onChange={(e) => onChange({ ...value, state: e.target.value })}
        >
          {STATES.map((s) => (
            <option key={s} value={s}>{s === "" ? "any" : s}</option>
          ))}
        </select>
      </label>

      <label className="filter-bar__field">
        <span className="filter-bar__label">Method</span>
        <select
          className="filter-bar__input"
          value={value.method}
          onChange={(e) => onChange({ ...value, method: e.target.value })}
        >
          {METHODS.map((m) => (
            <option key={m} value={m}>{m === "" ? "any" : m}</option>
          ))}
        </select>
      </label>

      <label className="filter-bar__field">
        <span className="filter-bar__label">Category</span>
        <input
          type="text"
          className="filter-bar__input"
          value={value.category}
          onChange={(e) => onChange({ ...value, category: e.target.value })}
          placeholder="e.g. injection"
        />
      </label>

      <label className="filter-bar__field filter-bar__field--grow">
        <span className="filter-bar__label">Search</span>
        <input
          type="text"
          className="filter-bar__input"
          value={value.q}
          onChange={(e) => onChange({ ...value, q: e.target.value })}
          placeholder="path / finding id / result text"
        />
      </label>

      <div className="filter-bar__count" aria-live="polite">
        {resultCount} / {totalCount}
      </div>
    </div>
  );
}
