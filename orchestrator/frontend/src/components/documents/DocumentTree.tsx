import type { DocumentTree as Tree, DocumentEntry } from "../../lib/api";

type DocumentTreeProps = {
  tree: Tree | null;
  selectedPath: string | null;
  onSelect: (path: string) => void;
};

const BUCKET_ORDER: (keyof Tree)[] = ["findings", "reports", "intel", "surface", "other"];
const BUCKET_LABEL: Record<keyof Tree, string> = {
  findings: "Findings",
  reports:  "Reports",
  intel:    "Intel",
  surface:  "Surface",
  other:    "Other",
};

export function DocumentTree({ tree, selectedPath, onSelect }: DocumentTreeProps) {
  if (tree === null) {
    return <div className="doc-tree__loading">Loading…</div>;
  }
  const totalFiles = BUCKET_ORDER.reduce(
    (n, b) => n + (tree[b]?.length ?? 0),
    0,
  );
  if (totalFiles === 0) {
    return <div className="doc-tree__empty">No documents in this run's engagement yet.</div>;
  }

  return (
    <nav className="doc-tree" aria-label="Documents">
      {BUCKET_ORDER.map((bucket) => {
        const entries = tree[bucket] ?? [];
        if (entries.length === 0) return null;
        return (
          <section key={bucket} className="doc-tree__bucket">
            <header className="doc-tree__bucket-head">
              <span className="doc-tree__bucket-name">{BUCKET_LABEL[bucket]}</span>
              <span className="doc-tree__bucket-count">{entries.length}</span>
            </header>
            <ul className="doc-tree__list">
              {entries.map((e) => (
                <DocumentNode
                  key={e.path}
                  entry={e}
                  selected={e.path === selectedPath}
                  onSelect={onSelect}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </nav>
  );
}

function DocumentNode({ entry, selected, onSelect }: {
  entry: DocumentEntry; selected: boolean; onSelect: (path: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={`doc-tree__node ${selected ? "doc-tree__node--selected" : ""}`}
        onClick={() => onSelect(entry.path)}
        aria-current={selected ? "true" : undefined}
      >
        <span className="doc-tree__name">{entry.name}</span>
        <span className="doc-tree__size">{sizeLabel(entry.size)}</span>
      </button>
    </li>
  );
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
