import { FormEvent, useMemo, useState } from "react";

import type { Project, Run } from "../lib/api";

type ProjectsPageProps = {
  username: string;
  projects: Project[];
  runsByProject: Record<number, Run[]>;
  onCreateProject: (name: string) => Promise<void>;
  onCreateRun: (projectId: number, target: string) => Promise<void>;
  onDeleteProject: (projectId: number) => Promise<void>;
  onDeleteRun: (projectId: number, runId: number) => Promise<void>;
  onOpenRun: (projectId: number, runId: number) => void;
  onLogout: () => void;
};

export function ProjectsPage({
  username,
  projects,
  runsByProject,
  onCreateProject,
  onCreateRun,
  onDeleteProject,
  onDeleteRun,
  onOpenRun,
  onLogout,
}: ProjectsPageProps) {
  const [projectName, setProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [runTargets, setRunTargets] = useState<Record<number, string>>({});
  const [creatingRunId, setCreatingRunId] = useState<number | null>(null);

  const totalRuns = useMemo(
    () => Object.values(runsByProject).reduce((count, runs) => count + runs.length, 0),
    [runsByProject],
  );

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingProject(true);
    setProjectError(null);
    try {
      await onCreateProject(projectName);
      setProjectName("");
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleCreateRun(event: FormEvent<HTMLFormElement>, projectId: number) {
    event.preventDefault();
    setCreatingRunId(projectId);
    try {
      await onCreateRun(projectId, runTargets[projectId] ?? "");
      setRunTargets((current) => ({ ...current, [projectId]: "" }));
    } finally {
      setCreatingRunId(null);
    }
  }

  async function handleDeleteProject(projectId: number) {
    if (!window.confirm("Delete this project and all of its runs?")) {
      return;
    }
    await onDeleteProject(projectId);
  }

  async function handleDeleteRun(projectId: number, runId: number) {
    if (!window.confirm("Delete this run and all of its files?")) {
      return;
    }
    await onDeleteRun(projectId, runId);
  }

  return (
    <main className="shell dashboard-shell">
      <section className="dashboard-header">
        <div>
          <p className="eyebrow">Overview</p>
          <h1>Projects</h1>
          <p className="lead">
            {username} owns {projects.length} project{projects.length === 1 ? "" : "s"} and {totalRuns} run
            {totalRuns === 1 ? "" : "s"}.
          </p>
        </div>
        <button className="ghost-button" onClick={onLogout}>
          Sign out
        </button>
      </section>

      <section className="dashboard-grid">
        <section className="panel">
          <h2>Create project</h2>
          <form onSubmit={handleCreateProject} className="stack">
            <label className="field">
              <span>Project name</span>
              <input
                placeholder="Acme external perimeter"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                required
              />
            </label>
            {projectError ? <p className="error-text">{projectError}</p> : null}
            <button type="submit" className="primary-button" disabled={creatingProject}>
              {creatingProject ? "Creating..." : "Create project"}
            </button>
          </form>
        </section>

        <section className="project-column">
          {projects.map((project) => (
            <article className="panel project-card" key={project.id}>
              <div className="project-heading">
                <div>
                  <h2>{project.name}</h2>
                  <p className="meta-text">{project.slug}</p>
                </div>
                <div className="project-actions">
                  <span className="badge">{runsByProject[project.id]?.length ?? 0} runs</span>
                  <button
                    type="button"
                    className="ghost-button danger-button"
                    onClick={() => void handleDeleteProject(project.id)}
                  >
                    Delete project
                  </button>
                </div>
              </div>
              <p className="path-text">{project.root_path}</p>

              <form className="run-form" onSubmit={(event) => handleCreateRun(event, project.id)}>
                <label className="field">
                  <span>Target</span>
                  <input
                    placeholder="https://target.example"
                    value={runTargets[project.id] ?? ""}
                    onChange={(event) =>
                      setRunTargets((current) => ({ ...current, [project.id]: event.target.value }))
                    }
                    required
                  />
                </label>
                <button
                  type="submit"
                  className="secondary-button"
                  disabled={creatingRunId === project.id}
                >
                  {creatingRunId === project.id ? "Queueing..." : "Queue run"}
                </button>
              </form>

              <div className="run-list">
                {(runsByProject[project.id] ?? []).map((run) => (
                  <div key={run.id} className="run-row">
                    <button
                      className="run-open-button"
                      onClick={() => onOpenRun(project.id, run.id)}
                      type="button"
                    >
                      <div>
                        <strong>{run.target}</strong>
                        <p className="meta-text">{run.engagement_root}</p>
                      </div>
                      <span className={`status-pill status-${run.status}`}>{run.status}</span>
                    </button>
                    <button
                      type="button"
                      className="ghost-button danger-button"
                      onClick={() => void handleDeleteRun(project.id, run.id)}
                    >
                      Delete
                    </button>
                  </div>
                ))}
                {(runsByProject[project.id] ?? []).length === 0 ? (
                  <p className="empty-state">No runs yet.</p>
                ) : null}
              </div>
            </article>
          ))}
          {projects.length === 0 ? <section className="panel empty-state">No projects yet.</section> : null}
        </section>
      </section>
    </main>
  );
}
