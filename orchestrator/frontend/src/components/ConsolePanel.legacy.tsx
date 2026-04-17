import type { ArtifactContent } from "../lib/api";

type ConsolePanelProps = {
  processLog: ArtifactContent | null;
};

export function ConsolePanel({ processLog }: ConsolePanelProps) {
  return (
    <section className="panel console-panel tall-panel">
      <div className="panel-header">
        <h2>Live console</h2>
        <p className="meta-text">Container output stream for the active all-in-one redteam runtime.</p>
      </div>
      <div className="console-output">
        {processLog ? <pre>{processLog.content}</pre> : <p className="empty-state">No console output yet.</p>}
      </div>
    </section>
  );
}
