import { useState } from "react";
import { listDocuments } from "../../lib/api";
import type { DocumentTree as Tree } from "../../lib/api";
import { useAutoRefresh } from "../../lib/useAutoRefresh";
import { DocumentTree } from "./DocumentTree";
import { DocumentPreview } from "./DocumentPreview";
import "./documents.css";

type DocumentsTabProps = {
  token: string;
  projectId: number;
  runId: number;
};

export function DocumentsTab({ token, projectId, runId }: DocumentsTabProps) {
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useAutoRefresh(
    async (signal) => {
      try {
        const t = await listDocuments(token, projectId, runId);
        if (signal.aborted) return;
        setTree(t);
        setError(null);
      } catch (err) {
        if (signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [token, projectId, runId],
    { intervalMs: 10_000 },  // Documents change slowly; 10s is fine.
  );

  return (
    <div className="documents" data-testid="documents-tab">
      <aside className="documents__side">
        {error && <div className="documents__error" role="alert">Failed to load: {error}</div>}
        <DocumentTree
          tree={tree}
          selectedPath={selectedPath}
          onSelect={setSelectedPath}
        />
      </aside>
      <main className="documents__main">
        <DocumentPreview
          token={token}
          projectId={projectId}
          runId={runId}
          path={selectedPath}
        />
      </main>
    </div>
  );
}
