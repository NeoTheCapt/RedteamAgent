import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getDocument } from "../../lib/api";

type DocumentPreviewProps = {
  token: string;
  projectId: number;
  runId: number;
  path: string | null;
};

const TEXT_EXTS = [
  ".md",
  ".markdown",
  ".txt",
  ".log",
  ".json",
  ".jsonl",
  ".csv",
  ".xml",
  ".yaml",
  ".yml",
  ".html",
  ".sh",
];

function isTextPath(path: string): boolean {
  const lower = path.toLowerCase();
  return TEXT_EXTS.some((ext) => lower.endsWith(ext));
}

function isMarkdown(path: string): boolean {
  const lower = path.toLowerCase();
  return lower.endsWith(".md") || lower.endsWith(".markdown");
}

export function DocumentPreview({
  token,
  projectId,
  runId,
  path,
}: DocumentPreviewProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (path === null) {
      setContent(null);
      setError(null);
      return;
    }
    if (!isTextPath(path)) {
      setContent(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDocument(token, projectId, runId, path)
      .then((doc) => {
        if (!cancelled) setContent(doc.content);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, projectId, runId, path]);

  if (path === null) {
    return (
      <div className="doc-preview doc-preview--empty">
        <p>Select a document from the left to preview.</p>
      </div>
    );
  }
  if (!isTextPath(path)) {
    return (
      <div className="doc-preview doc-preview--empty">
        <header className="doc-preview__head">
          <span className="doc-preview__path">{path}</span>
        </header>
        <p className="doc-preview__binary">
          Binary file — preview not available. The run's engagement directory
          still contains the original file on disk.
        </p>
      </div>
    );
  }
  return (
    <div className="doc-preview">
      <header className="doc-preview__head">
        <span className="doc-preview__path">{path}</span>
      </header>
      {loading && <div className="doc-preview__loading">Loading…</div>}
      {error && (
        <div className="doc-preview__error" role="alert">
          Failed to load: {error}
        </div>
      )}
      {!loading && !error && content !== null && (
        isMarkdown(path) ? (
          <article className="doc-preview__md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </article>
        ) : (
          <pre className="doc-preview__pre">{content}</pre>
        )
      )}
    </div>
  );
}
