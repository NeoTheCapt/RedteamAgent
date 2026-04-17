import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  Artifact,
  ArtifactContent,
  EventRecord,
  ObservedPathRecord,
  Run,
  createWebSocketTicket,
  getRunSummary,
  listArtifacts,
  listEvents,
  listObservedPaths,
  listRuns,
  readArtifact,
  runWebSocketUrl,
  RunSummary,
} from "../lib/api";
import { ArtifactViewer } from "../components/ArtifactViewer";
import { ConsolePanel } from "../components/ConsolePanel";
import { LogPanel } from "../components/LogPanel";
import { PhaseWaterfall } from "../components/PhaseWaterfall";
import { RunSummaryCards } from "../components/RunSummaryCards";
import { SubagentBoard } from "../components/SubagentBoard";
import { TabBar } from "../components/TabBar";
import { TaskTimeline } from "../components/TaskTimeline";

type RunPageProps = {
  token: string;
  projectId: number;
  runId: number;
  onBack: () => void;
  onDeleteRun: (projectId: number, runId: number) => Promise<void>;
};

export function RunPage({ token, projectId, runId, onBack, onDeleteRun }: RunPageProps) {
  const tabs = [
    { id: "mission", label: "Mission" },
    { id: "agents", label: "Agents" },
    { id: "documents", label: "Documents" },
    { id: "logs", label: "Logs" },
    { id: "console", label: "Console" },
  ] as const;
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactContent | null>(null);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [observedPaths, setObservedPaths] = useState<ObservedPathRecord[]>([]);
  const [showObservedPaths, setShowObservedPaths] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("mission");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [runMissing, setRunMissing] = useState(false);
  const displayCurrentPhase =
    !summary?.current.phase || summary.current.phase === "unknown" ? "initializing" : summary.current.phase;

  function handleRunNotFound(error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      setRunMissing(true);
      setRun(null);
      setEvents([]);
      setArtifacts([]);
      setSummary(null);
      setSelectedArtifact(null);
      setSelectedName(null);
      return true;
    }
    return false;
  }

  function refreshArtifacts() {
    return listArtifacts(token, projectId, runId)
      .then((nextArtifacts) => {
        setArtifacts(nextArtifacts);
        if (!selectedName) {
          const firstAvailable = nextArtifacts.find((artifact) => artifact.exists);
          if (firstAvailable) {
            setSelectedName(firstAvailable.name);
          }
        }
      })
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          throw error;
        }
      });
  }

  function refreshSelectedArtifact(name: string) {
    return readArtifact(token, projectId, runId, name)
      .then(setSelectedArtifact)
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          setSelectedArtifact(null);
        }
      });
  }

  function refreshRunState() {
    return listRuns(token, projectId)
      .then((runs) => {
        const nextRun = runs.find((candidate) => candidate.id === runId) ?? null;
        if (!nextRun) {
          setRunMissing(true);
          setRun(null);
          return;
        }
        setRun(nextRun);
      })
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          throw error;
        }
      });
  }

  function refreshEvents() {
    return listEvents(token, projectId, runId)
      .then(setEvents)
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          throw error;
        }
      });
  }

  function refreshSummary() {
    return getRunSummary(token, projectId, runId)
      .then(setSummary)
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          throw error;
        }
      });
  }

  function refreshObservedPaths() {
    return listObservedPaths(token, projectId, runId)
      .then(setObservedPaths)
      .catch((error) => {
        if (!handleRunNotFound(error)) {
          throw error;
        }
      });
  }

  useEffect(() => {
    if (runMissing) {
      onBack();
    }
  }, [onBack, runMissing]);

  useEffect(() => {
    refreshRunState();
    refreshEvents();
    refreshSummary();
    refreshObservedPaths();
    refreshArtifacts();
  }, [projectId, runId, token]);

  useEffect(() => {
    if (runMissing) {
      return;
    }
    if (!selectedName) {
      setSelectedArtifact(null);
      return;
    }
    refreshSelectedArtifact(selectedName);
  }, [projectId, runId, runMissing, selectedName, token]);

  const artifactTabArtifacts = useMemo(
    () => artifacts.filter((artifact) => !["log.md", "process.log"].includes(artifact.name)),
    [artifacts],
  );
  const logArtifacts = useMemo(
    () => ({
      engagement: artifacts.find((artifact) => artifact.name === "log.md" && artifact.exists) ?? null,
      runtime: artifacts.find((artifact) => artifact.name === "process.log" && artifact.exists) ?? null,
    }),
    [artifacts],
  );

  useEffect(() => {
      const availableArtifacts =
        activeTab === "documents"
          ? artifactTabArtifacts
        : activeTab === "logs"
          ? [logArtifacts.engagement].filter(Boolean) as Artifact[]
          : activeTab === "console"
          ? [logArtifacts.engagement, logArtifacts.runtime].filter(Boolean) as Artifact[]
          : artifacts;
    if (availableArtifacts.length === 0) {
      setSelectedName(null);
      return;
    }
    if (!selectedName || !availableArtifacts.some((artifact) => artifact.name === selectedName && artifact.exists)) {
      const preferredLog =
        activeTab === "logs"
          ? availableArtifacts.find((artifact) => artifact.name === "log.md" && artifact.exists)
          : activeTab === "console"
            ? availableArtifacts.find((artifact) => artifact.name === "process.log" && artifact.exists)
            : null;
      const firstAvailable = preferredLog ?? availableArtifacts.find((artifact) => artifact.exists);
      setSelectedName(firstAvailable?.name ?? null);
    }
  }, [activeTab, artifactTabArtifacts, artifacts, logArtifacts, selectedName]);

  useEffect(() => {
    if (runMissing) {
      return;
    }
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
        void refreshSummary();
        void refreshObservedPaths();
        void refreshArtifacts();
        if (selectedName) {
          void refreshSelectedArtifact(selectedName);
        }
      };
    }

    void connect().catch((error) => {
      if (!handleRunNotFound(error)) {
        console.error(error);
      }
    });

    return () => {
      cancelled = true;
      socket?.close();
    };
  }, [projectId, runId, runMissing, selectedName, token]);

  useEffect(() => {
    if (runMissing) {
      return;
    }
    const interval = window.setInterval(() => {
      void refreshRunState();
      void refreshEvents();
      void refreshSummary();
      void refreshObservedPaths();
      void refreshArtifacts();
      if (selectedName) {
        void refreshSelectedArtifact(selectedName);
      }
    }, 3000);

    return () => window.clearInterval(interval);
  }, [projectId, runId, runMissing, selectedName, token]);

  const latestSummary = useMemo(
    () => summary?.current.summary ?? events.at(-1)?.summary ?? "Waiting for events",
    [events, summary],
  );
  const targetScope = summary?.target.scope_entries ?? [];
  const currentAgentName = summary?.current.agent_name || "operator";
  const currentTaskName = summary?.current.task_name || "No task assigned yet";
  const currentTaskSummary = summary?.current.summary || "Waiting for the next structured event.";

  async function handleDeleteRun() {
    if (!window.confirm("Delete this run and all of its files?")) {
      return;
    }
    await onDeleteRun(projectId, runId);
  }

  return (
    <main className="shell run-shell">
      <section className="dashboard-header">
        <div>
          <p className="eyebrow">Mission Control</p>
          <h1>{run?.target ?? `Run #${runId}`}</h1>
          <p className="lead">{latestSummary}</p>
        </div>
        <div className="page-actions">
          <button className="ghost-button danger-button" onClick={() => void handleDeleteRun()}>
            Delete run
          </button>
          <button className="ghost-button" onClick={onBack}>
            Back to projects
          </button>
        </div>
      </section>

      <section className="run-overview panel">
        <div>
          <span className={`status-pill status-${run?.status ?? "queued"}`}>{run?.status ?? "queued"}</span>
          <p className="meta-text">{summary?.target.engagement_dir ?? run?.engagement_root ?? "Pending engagement root"}</p>
        </div>
      </section>

      <TabBar tabs={[...tabs]} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "mission" ? (
        <>
          <section className="panel mission-hero">
            <div className="mission-hero-main">
              <div>
                <p className="eyebrow">Target briefing</p>
                <h2>{summary?.target.hostname ?? run?.target ?? "Pending target"}</h2>
                <p className="lead">
                  {summary
                    ? `${summary.target.scheme}://${summary.target.hostname}:${summary.target.port}${summary.target.path}`
                    : "Waiting for run metadata."}
                </p>
              </div>
              <div className="mission-hero-badges">
                <span className={`status-pill status-${run?.status ?? "queued"}`}>{run?.status ?? "queued"}</span>
                <span className="badge">{displayCurrentPhase}</span>
                <span className="badge">{currentAgentName}</span>
              </div>
            </div>
            <div className="mission-hero-grid">
              <article className="mission-hero-card">
                <p className="eyebrow">Current task</p>
                <strong>{currentTaskName}</strong>
                <p>{currentTaskSummary}</p>
              </article>
              <article className="mission-hero-card">
                <p className="eyebrow">Scope</p>
                <strong>{targetScope[0] ?? "No explicit scope yet"}</strong>
                <p>{targetScope.slice(1).join(", ") || "Single target scope."}</p>
              </article>
              <article className="mission-hero-card">
                <p className="eyebrow">Coverage pressure</p>
                <strong>{summary?.coverage.high_risk_remaining ?? 0} high-risk remaining</strong>
                <p>
                  {summary
                    ? `${summary.coverage.processing_cases} processing · ${summary.coverage.pending_cases} pending`
                    : "Waiting for case telemetry."}
                </p>
              </article>
            </div>
          </section>

          <RunSummaryCards summary={summary} />

          <section className="mission-columns">
            <div className="mission-column">
              <PhaseWaterfall summary={summary} />
              <section className="panel metric-panel tall-panel">
                <div className="panel-header">
                  <h2>Observed path types</h2>
                  <div className="panel-header-actions">
                    <p className="meta-text">Derived from cases.db and surface tracking</p>
                    <button type="button" className="ghost-button compact-button" onClick={() => setShowObservedPaths(true)}>
                      View full list
                    </button>
                  </div>
                </div>
                <div className="metric-list">
                  {(summary?.coverage.case_types ?? []).map((entry) => (
                    <article key={entry.type} className="metric-row">
                      <div>
                        <strong>{entry.type}</strong>
                        <p className="meta-text">
                          {entry.done ?? 0} done · {entry.pending ?? 0} pending · {entry.processing ?? 0} processing · {entry.error ?? 0} error
                        </p>
                      </div>
                      <span className="badge">{entry.total ?? 0}</span>
                    </article>
                  ))}
                  {(summary?.coverage.case_types ?? []).length === 0 ? (
                    <p className="empty-state">No case metrics yet.</p>
                  ) : null}
                </div>
              </section>
            </div>

            <div className="mission-column">
              <section className="panel mission-briefing-panel">
                <div className="panel-header">
                  <h2>Mission status</h2>
                  <p className="meta-text">Live execution posture and technical indicators</p>
                </div>
                <div className="current-action-card mission-callout">
                  <p className="eyebrow">{displayCurrentPhase}</p>
                  <h3>{currentAgentName}</h3>
                  <p>{currentTaskSummary}</p>
                  <p className="meta-text">{currentTaskName}</p>
                </div>
                <div className="target-card">
                  <h3>Target profile</h3>
                  <p className="meta-text">{summary?.target.target ?? run?.target ?? "Pending target"}</p>
                  <p>{targetScope.join(", ") || "No explicit scope entries yet"}</p>
                </div>
                <div className="coverage-breakdown">
                  <h3>Technical indicators</h3>
                  <div className="coverage-grid">
                    <article>
                      <strong>{summary?.coverage.total_cases ?? 0}</strong>
                      <span>Paths observed</span>
                    </article>
                    <article>
                      <strong>{summary?.coverage.completed_cases ?? 0}</strong>
                      <span>Completed checks</span>
                    </article>
                    <article>
                      <strong>{summary?.coverage.remaining_surfaces ?? 0}</strong>
                      <span>Remaining surfaces</span>
                    </article>
                    <article>
                      <strong>{summary?.coverage.high_risk_remaining ?? 0}</strong>
                      <span>High-risk remaining</span>
                    </article>
                  </div>
                </div>
              </section>

              <section className="panel metric-panel tall-panel">
                <div className="panel-header">
                  <h2>Surface types</h2>
                  <p className="meta-text">High-risk discovery coverage</p>
                </div>
                <div className="metric-list">
                  {(summary?.coverage.surface_types ?? []).map((entry) => (
                    <article key={entry.type} className="metric-row">
                      <div>
                        <strong>{entry.type}</strong>
                      </div>
                      <span className="badge">{entry.count ?? 0}</span>
                    </article>
                  ))}
                  {(summary?.coverage.surface_types ?? []).length === 0 ? (
                    <p className="empty-state">No surface metrics yet.</p>
                  ) : null}
                </div>
              </section>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === "agents" ? (
        <section className="mission-grid mission-grid-agents">
          <SubagentBoard summary={summary} selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />
          <TaskTimeline events={events} selectedAgent={selectedAgent} />
        </section>
      ) : null}

      {activeTab === "documents" ? (
        <ArtifactViewer
          artifacts={artifactTabArtifacts}
          selectedName={selectedName}
          selectedArtifact={selectedArtifact}
          onSelect={setSelectedName}
        />
      ) : null}

      {activeTab === "logs" ? (
        <LogPanel engagementLog={selectedName === "log.md" ? selectedArtifact : null} />
      ) : null}

      {activeTab === "console" ? (
        <ConsolePanel processLog={selectedName === "process.log" ? selectedArtifact : null} />
      ) : null}

      {showObservedPaths ? (
        <div className="modal-backdrop" onClick={() => setShowObservedPaths(false)}>
          <section className="modal-card observed-paths-modal" onClick={(event) => event.stopPropagation()}>
            <div className="panel-header">
              <div>
                <h2>Observed paths</h2>
                <p className="meta-text">Complete current cases.db list for this run.</p>
              </div>
              <button type="button" className="ghost-button compact-button" onClick={() => setShowObservedPaths(false)}>
                Close
              </button>
            </div>
            <div className="observed-paths-table">
              <div className="observed-paths-head">
                <span>Method</span>
                <span>Type</span>
                <span>Status</span>
                <span>Agent</span>
                <span>Source</span>
                <span>URL</span>
              </div>
              <div className="observed-paths-body">
                {observedPaths.map((entry, index) => (
                  <article key={`${entry.method}-${entry.url}-${index}`} className="observed-path-row">
                    <span className="badge">{entry.method}</span>
                    <span>{entry.type}</span>
                    <span>{entry.status}</span>
                    <span>{entry.assigned_agent || "Unassigned"}</span>
                    <span>{entry.source || "Unknown"}</span>
                    <code>{entry.url}</code>
                  </article>
                ))}
                {observedPaths.length === 0 ? <p className="empty-state">No observed paths recorded yet.</p> : null}
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
