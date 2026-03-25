import type { Artifact, ArtifactContent } from "../lib/api";

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
  return (
    <section className="panel artifact-panel">
      <div className="panel-header">
        <h2>Artifacts</h2>
        <p className="meta-text">Documents and engagement outputs</p>
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
              <pre>{selectedArtifact.content}</pre>
            </>
          ) : (
            <p className="empty-state">Select an available artifact to inspect it.</p>
          )}
        </article>
      </div>
    </section>
  );
}
