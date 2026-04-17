import type { Artifact, ArtifactContent } from "../lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type ArtifactViewerProps = {
  artifacts: Artifact[];
  selectedName: string | null;
  selectedArtifact: ArtifactContent | null;
  onSelect: (name: string) => void;
};

export function ArtifactViewer({
  artifacts,
  selectedName,
  selectedArtifact,
  onSelect,
}: ArtifactViewerProps) {
  function isMarkdownArtifact(artifact: ArtifactContent) {
    return artifact.media_type === "text/markdown" || artifact.name.toLowerCase().endsWith(".md");
  }

  function renderArtifactContent() {
    if (!selectedArtifact) {
      return <p className="empty-state">Select an available artifact to inspect it.</p>;
    }

    if (selectedArtifact.name === "log.md") {
      const sections = selectedArtifact.content
        .split(/\n(?=## \[\d{2}:\d{2}\])/)
        .map((section) => section.trim())
        .filter(Boolean)
        .reverse();
      return (
        <div className="log-stack">
          {sections.map((section, index) => (
            <pre key={`${index}-${section.slice(0, 24)}`}>{section}</pre>
          ))}
        </div>
      );
    }

    if (isMarkdownArtifact(selectedArtifact)) {
      return (
        <div className="markdown-document">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedArtifact.content}</ReactMarkdown>
        </div>
      );
    }

    return <pre>{selectedArtifact.content}</pre>;
  }

  return (
    <section className="panel artifact-panel document-panel">
      <div className="panel-header">
        <h2>Documents</h2>
        <p className="meta-text">Evidence, findings, notes, and generated outputs.</p>
      </div>
      <div className="artifact-layout">
        <aside className="artifact-list">
          {artifacts.map((artifact) => (
            <button
              key={artifact.name}
              type="button"
              className={`artifact-row ${selectedName === artifact.name ? "artifact-active" : ""}`}
              disabled={!artifact.exists}
              onClick={() => onSelect(artifact.name)}
            >
              <div>
                <strong>{artifact.name}</strong>
                <p className="meta-text">{artifact.relative_path}</p>
              </div>
              <div className="artifact-tags">
                {artifact.sensitive ? <span className="badge badge-warn">Sensitive</span> : null}
                <span className="badge">{artifact.exists ? "Available" : "Missing"}</span>
              </div>
            </button>
          ))}
        </aside>
        <article className="artifact-content">
          {selectedArtifact ? (
            <>
              <div className="artifact-content-header">
                <strong>{selectedArtifact.name}</strong>
                <span className="meta-text">{selectedArtifact.media_type}</span>
              </div>
              {renderArtifactContent()}
            </>
          ) : renderArtifactContent()}
        </article>
      </div>
    </section>
  );
}
