import { useEffect, useMemo, useState } from "react";
import type { Case, CaseListFilter } from "../../lib/api";
import { listCases } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { parseHashQuery, encodeHashQuery } from "../../lib/hashQuery";
import { FilterBar, type FilterValues } from "./FilterBar";
import { CasesTable } from "./CasesTable";
import { CaseSidePanel } from "./CaseSidePanel";
import "./cases.css";

type CasesTabProps = {
  token: string;
  projectId: number;
  runId: number;
};

function readFiltersFromHash(): FilterValues {
  const { query } = parseHashQuery(window.location.hash);
  return {
    state: query.state ?? "",
    method: query.method ?? "",
    category: query.category ?? "",
    q: query.q ?? "",
  };
}

function writeFiltersToHash(next: FilterValues) {
  const { path } = parseHashQuery(window.location.hash);
  const newHash = encodeHashQuery(path, {
    state: next.state || undefined,
    method: next.method || undefined,
    category: next.category || undefined,
    q: next.q || undefined,
  });
  if (newHash !== window.location.hash.replace(/^#/, "")) {
    window.history.replaceState(null, "", "#" + newHash);
  }
}

function matchSearch(c: Case, q: string): boolean {
  if (!q) return true;
  const lc = q.toLowerCase();
  return (
    c.path.toLowerCase().includes(lc) ||
    (c.result?.toLowerCase().includes(lc) ?? false) ||
    (c.finding_id?.toLowerCase().includes(lc) ?? false)
  );
}

export function CasesTab({ token, projectId, runId }: CasesTabProps) {
  const [filters, setFilters] = useState<FilterValues>(() => readFiltersFromHash());
  const [cases, setCases] = useState<Case[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Derive backend filters (state/method/category server-side; q client-side)
  const serverFilter: CaseListFilter = useMemo(() => ({
    state: filters.state || undefined,
    method: filters.method || undefined,
    category: filters.category || undefined,
  }), [filters.state, filters.method, filters.category]);

  useAutoRefresh(
    async (signal) => {
      try {
        const rows = await listCases(token, projectId, runId, serverFilter);
        if (signal.aborted) return;
        setCases(rows);
        setError(null);
      } catch (err) {
        if (signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [token, projectId, runId, serverFilter.state, serverFilter.method, serverFilter.category],
  );

  const filtered = useMemo(
    () => cases.filter((c) => matchSearch(c, filters.q)),
    [cases, filters.q],
  );

  function onFilterChange(next: FilterValues) {
    setFilters(next);
    writeFiltersToHash(next);
  }

  // If the selected case disappears from the filtered set (e.g. filter change),
  // close the side panel.
  useEffect(() => {
    if (selectedId !== null && !filtered.some((c) => c.case_id === selectedId)) {
      setSelectedId(null);
    }
  }, [filtered, selectedId]);

  return (
    <div className="cases" data-testid="cases-tab">
      <div className="cases__main">
        <FilterBar
          value={filters}
          onChange={onFilterChange}
          resultCount={filtered.length}
          totalCount={cases.length}
        />
        {error && <div className="case-side__error" role="alert">Failed to load: {error}</div>}
        <CasesTable
          cases={filtered}
          selectedId={selectedId}
          onSelect={(id) => setSelectedId((prev) => (prev === id ? null : id))}
        />
      </div>
      {selectedId !== null && (
        <div className="cases__side">
          <CaseSidePanel
            token={token}
            projectId={projectId}
            runId={runId}
            caseId={selectedId}
            onClose={() => setSelectedId(null)}
          />
        </div>
      )}
    </div>
  );
}
