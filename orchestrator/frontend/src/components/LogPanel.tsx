import type { ArtifactContent } from "../lib/api";

type LogPanelProps = {
  engagementLog: ArtifactContent | null;
};

function renderLogSections(content: string) {
  return content
    .split(/\n(?=## \[\d{2}:\d{2}\])/)
    .map((section) => section.trim())
    .filter(Boolean)
    .reverse();
}

export function LogPanel({ engagementLog }: LogPanelProps) {
  const engagementSections = engagementLog ? renderLogSections(engagementLog.content) : [];

  return (
    <section className="panel log-panel tall-panel">
      <div className="panel-header">
        <h2>Engagement log</h2>
        <p className="meta-text">Chronology view with newest entries pinned on top.</p>
      </div>
      <div className="log-stack">
        {engagementSections.map((section, index) => (
          <pre key={`${index}-${section.slice(0, 24)}`}>{section}</pre>
        ))}
        {engagementSections.length === 0 ? (
          <p className="empty-state">No engagement log entries yet.</p>
        ) : null}
      </div>
    </section>
  );
}
