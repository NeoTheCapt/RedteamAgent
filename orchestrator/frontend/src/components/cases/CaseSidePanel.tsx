import { useEffect, useState } from "react";
import type { Case } from "../../lib/api";
import { getCase } from "../../lib/api";
import { formatDuration } from "../../lib/formatDuration";

type CaseSidePanelProps = {
  token: string;
  projectId: number;
  runId: number;
  caseId: number;
  onClose: () => void;
};

export function CaseSidePanel({
  token, projectId, runId, caseId, onClose,
}: CaseSidePanelProps) {
  const [data, setData] = useState<Case | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getCase(token, projectId, runId, caseId)
      .then((c) => { if (!cancelled) setData(c); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); });
    return () => { cancelled = true; };
  }, [token, projectId, runId, caseId]);

  return (
    <aside className="case-side" aria-label={`Case ${caseId}`}>
      <header className="case-side__head">
        <div>
          <div className="case-side__label">Case</div>
          <div className="case-side__id">#{caseId}</div>
        </div>
        <button type="button" className="case-side__close" onClick={onClose}
          aria-label="Close detail">✕</button>
      </header>

      {error && <div className="case-side__error" role="alert">Failed to load: {error}</div>}
      {!error && !data && <div className="case-side__loading">Loading…</div>}
      {data && (
        <dl className="case-side__body">
          <dt>Method</dt>
          <dd><span className="case-side__badge">{data.method}</span></dd>

          <dt>Path</dt>
          <dd className="case-side__mono">{data.path}</dd>

          <dt>State</dt>
          <dd className={`case-side__state case-side__state--${data.state}`}>
            {data.state}
          </dd>

          <dt>Category</dt>
          <dd>{data.category ?? "—"}</dd>

          <dt>Dispatch</dt>
          <dd className="case-side__mono">{data.dispatch_id ?? "—"}</dd>

          <dt>Result</dt>
          <dd>{data.result ?? "—"}</dd>

          <dt>Finding</dt>
          <dd className={data.finding_id ? "case-side__finding" : ""}>
            {data.finding_id ?? "—"}
          </dd>

          <dt>Started</dt>
          <dd>{data.started_at !== null ? new Date(data.started_at * 1000).toISOString() : "—"}</dd>

          <dt>Finished</dt>
          <dd>{data.finished_at !== null ? new Date(data.finished_at * 1000).toISOString() : "—"}</dd>

          <dt>Duration</dt>
          <dd>{formatDuration(data.duration_ms)}</dd>
        </dl>
      )}
    </aside>
  );
}
