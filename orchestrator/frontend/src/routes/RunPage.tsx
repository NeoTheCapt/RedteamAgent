import { useEffect, useMemo, useState } from "react";

import {
  Artifact,
  ArtifactContent,
  EventRecord,
  Run,
  createWebSocketTicket,
  listArtifacts,
  listEvents,
  listRuns,
  readArtifact,
  runWebSocketUrl,
} from "../lib/api";
import { ArtifactViewer } from "../components/ArtifactViewer";
import { PhaseWaterfall } from "../components/PhaseWaterfall";
import { TaskTimeline } from "../components/TaskTimeline";

type RunPageProps = {
  token: string;
  projectId: number;
  runId: number;
  onBack: () => void;
};

export function RunPage({ token, projectId, runId, onBack }: RunPageProps) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactContent | null>(null);

  function refreshArtifacts() {
    listArtifacts(token, projectId, runId).then((nextArtifacts) => {
      setArtifacts(nextArtifacts);
      if (!selectedName) {
        const firstAvailable = nextArtifacts.find((artifact) => artifact.exists);
        if (firstAvailable) {
          setSelectedName(firstAvailable.name);
        }
      }
    });
  }

  function refreshSelectedArtifact(name: string) {
    readArtifact(token, projectId, runId, name)
      .then(setSelectedArtifact)
      .catch(() => setSelectedArtifact(null));
  }

  useEffect(() => {
    listRuns(token, projectId).then((runs) => {
      setRun(runs.find((candidate) => candidate.id === runId) ?? null);
    });
    listEvents(token, projectId, runId).then(setEvents);
    refreshArtifacts();
  }, [projectId, runId, token]);

  useEffect(() => {
    if (!selectedName) {
      setSelectedArtifact(null);
      return;
    }
    refreshSelectedArtifact(selectedName);
  }, [projectId, runId, selectedName, token]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    async function connect() {
      const ticket = await createWebSocketTicket(token);
      if (cancelled) {
        return;
      }

      socket = new WebSocket(runWebSocketUrl(projectId, runId, ticket.ticket));
      socket.onmessage = (message) => {
        const payload = JSON.parse(message.data);
        if (payload.type === "event.created") {
          setEvents((current) => [...current, payload.event as EventRecord]);
        }
        if (payload.type === "run.status.updated") {
          setRun(payload.run as Run);
        }
        refreshArtifacts();
        if (selectedName) {
          refreshSelectedArtifact(selectedName);
        }
      };
    }

    void connect();

    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [projectId, runId, token]);

  const latestSummary = useMemo(() => events.at(-1)?.summary ?? "Waiting for events", [events]);

  return (
    <main className="shell run-shell">
      <section className="dashboard-header">
        <div>
          <p className="eyebrow">Run detail</p>
          <h1>{run?.target ?? `Run #${runId}`}</h1>
          <p className="lead">{latestSummary}</p>
        </div>
        <button className="ghost-button" onClick={onBack}>
          Back to projects
        </button>
      </section>

      <section className="run-overview panel">
        <div>
          <span className={`status-pill status-${run?.status ?? "queued"}`}>{run?.status ?? "queued"}</span>
          <p className="meta-text">{run?.engagement_root ?? "Pending engagement root"}</p>
        </div>
      </section>

      <PhaseWaterfall events={events} />

      <section className="run-grid">
        <TaskTimeline events={events} />
        <ArtifactViewer
          artifacts={artifacts}
          selectedName={selectedName}
          selectedArtifact={selectedArtifact}
          onSelect={setSelectedName}
        />
      </section>
    </main>
  );
}
