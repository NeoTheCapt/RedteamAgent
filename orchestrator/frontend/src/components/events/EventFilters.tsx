export type EventFilterValues = {
  level: string;      // "" | "info" | "warn" | "error" | ...
  kind: string;       // "" | "dispatch_start" | "case_done" | "finding" | ...
  source: string;     // agent_name substring
  search: string;     // free-text match over summary
};

type EventFiltersProps = {
  value: EventFilterValues;
  onChange: (next: EventFilterValues) => void;
  totalCount: number;
  filteredCount: number;
  paused: boolean;
  onTogglePause: () => void;
};

const LEVELS = ["", "info", "warn", "error", "ok", "debug", "find"] as const;
const KINDS = ["", "dispatch_start", "dispatch_done", "case_done", "finding", "phase_enter", "legacy"] as const;

export function EventFilters({
  value, onChange, totalCount, filteredCount, paused, onTogglePause,
}: EventFiltersProps) {
  return (
    <div className="event-filters" role="group" aria-label="Event filters">
      <label className="event-filters__field">
        <span className="event-filters__label">Level</span>
        <select
          className="event-filters__input"
          value={value.level}
          onChange={(e) => onChange({ ...value, level: e.target.value })}
        >
          {LEVELS.map((l) => <option key={l} value={l}>{l === "" ? "any" : l}</option>)}
        </select>
      </label>

      <label className="event-filters__field">
        <span className="event-filters__label">Kind</span>
        <select
          className="event-filters__input"
          value={value.kind}
          onChange={(e) => onChange({ ...value, kind: e.target.value })}
        >
          {KINDS.map((k) => <option key={k} value={k}>{k === "" ? "any" : k}</option>)}
        </select>
      </label>

      <label className="event-filters__field">
        <span className="event-filters__label">Source</span>
        <input
          className="event-filters__input"
          type="text"
          value={value.source}
          onChange={(e) => onChange({ ...value, source: e.target.value })}
          placeholder="e.g. vuln-analyst"
        />
      </label>

      <label className="event-filters__field event-filters__field--grow">
        <span className="event-filters__label">Search</span>
        <input
          className="event-filters__input"
          type="text"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
          placeholder="summary / task / phase"
        />
      </label>

      <div className="event-filters__actions">
        <button
          type="button"
          className={`event-filters__pause ${paused ? "event-filters__pause--on" : ""}`}
          onClick={onTogglePause}
          aria-pressed={paused}
        >
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <span className="event-filters__count" aria-live="polite">
          {filteredCount} / {totalCount}
        </span>
      </div>
    </div>
  );
}
