import type { Case } from "../../lib/api";

type CaseChipProps = {
  case_: Case;
  expanded: boolean;
  onToggle: () => void;
};

function stateGlyph(state: string): string {
  switch (state) {
    case "done":     return "✓";
    case "finding":  return "⚠";
    case "running":  return "▶";
    case "queued":   return "○";
    case "error":    return "!";
    default:         return "·";
  }
}

export function CaseChip({ case_: c, expanded, onToggle }: CaseChipProps) {
  const stateClass = `case-chip--${c.state}`;
  const short = shortenPath(c.path);
  const findingSuffix = c.finding_id ? " ⚠" : "";

  return (
    <div className={`case-chip ${stateClass} ${expanded ? "case-chip--open" : ""}`}>
      <button
        type="button"
        className="case-chip__button"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="case-chip__glyph" aria-hidden>{stateGlyph(c.state)}</span>
        <span className="case-chip__method">{c.method}</span>
        <span className="case-chip__path">{short}</span>
        <span className="case-chip__suffix">{findingSuffix}</span>
      </button>
      {expanded && (
        <div className="case-chip__detail">
          <div className="case-chip__row">
            <span className="case-chip__label">case</span>
            <span className="case-chip__value">#{c.case_id}</span>
          </div>
          <div className="case-chip__row">
            <span className="case-chip__label">endpoint</span>
            <span className="case-chip__value case-chip__value--mono">{c.method} {c.path}</span>
          </div>
          {c.category && (
            <div className="case-chip__row">
              <span className="case-chip__label">category</span>
              <span className="case-chip__value">{c.category}</span>
            </div>
          )}
          {c.result && (
            <div className="case-chip__row">
              <span className="case-chip__label">result</span>
              <span className="case-chip__value">{c.result}</span>
            </div>
          )}
          {c.finding_id && (
            <div className="case-chip__row">
              <span className="case-chip__label">finding</span>
              <span className="case-chip__value case-chip__value--finding">{c.finding_id}</span>
            </div>
          )}
          {c.duration_ms !== null && c.duration_ms !== undefined && (
            <div className="case-chip__row">
              <span className="case-chip__label">duration</span>
              <span className="case-chip__value">{c.duration_ms}ms</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function shortenPath(path: string, max = 30): string {
  if (path.length <= max) return path;
  return path.slice(0, max - 1) + "…";
}
