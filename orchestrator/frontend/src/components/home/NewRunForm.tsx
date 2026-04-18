import { FormEvent, useEffect, useState } from "react";
import type { Project } from "../../lib/api";
import "./NewRunForm.css";

type NewRunFormProps = {
  projects: Project[];
  onCreateRun: (projectId: number, target: string) => Promise<void>;
  onCreateProject: (name: string) => Promise<void>;
};

export function NewRunForm({ projects, onCreateRun, onCreateProject }: NewRunFormProps) {
  const [projectId, setProjectId] = useState<number | "">(projects[0]?.id ?? "");
  const [target, setTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync projectId when projects arrive asynchronously (useState initializer
  // only runs once, so if projects=[] on mount and populates later, projectId
  // would stay "" without this effect).
  useEffect(() => {
    if (projectId === "" && projects.length > 0) {
      setProjectId(projects[0].id);
    }
  }, [projects, projectId]);

  const [newProjectName, setNewProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  // Expand the create-project block automatically when no projects exist.
  const [createOpen, setCreateOpen] = useState(projects.length === 0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (typeof projectId !== "number" || !target.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreateRun(projectId, target.trim());
      setTarget("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCreateProject() {
    const name = newProjectName.trim();
    if (!name) return;
    setCreatingProject(true);
    setProjectError(null);
    try {
      await onCreateProject(name);
      setNewProjectName("");
      // Do NOT close the block automatically — let the user see the new project
      // appear in the dropdown below before they decide whether to create another.
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreatingProject(false);
    }
  }

  return (
    <form className="new-run" onSubmit={onSubmit} aria-label="New Run">
      <header className="new-run__head">
        <h1 className="new-run__title">New Engagement</h1>
        <p className="new-run__sub">
          Select a project and a target URL. Agent + crawler config is inherited
          from the project; advanced overrides arrive in a later plan.
        </p>
      </header>

      <section className="new-run__section">
        <header className="new-run__section-head">
          <h2 className="new-run__sec-title">Project</h2>
          <button
            type="button"
            className="new-run__link"
            onClick={() => setCreateOpen((v) => !v)}
            aria-expanded={createOpen}
          >
            {createOpen ? "Hide" : "+ Create project"}
          </button>
        </header>

        {createOpen && (
          <div className="new-run__create-project">
            <label className="new-run__field">
              <span className="new-run__label">New project name</span>
              <input
                className="new-run__input"
                type="text"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void handleCreateProject();
                  }
                }}
                placeholder="e.g. juice-shop-lab"
                disabled={creatingProject}
              />
              <span className="new-run__hint">
                Advanced configuration (provider, model, API key, scope, env) can
                be edited from the project settings — coming in a later plan.
              </span>
            </label>
            {projectError && (
              <div className="new-run__error" role="alert">{projectError}</div>
            )}
            <div className="new-run__inline-actions">
              <button
                type="button"
                className="new-run__secondary"
                onClick={() => void handleCreateProject()}
                disabled={creatingProject || !newProjectName.trim()}
              >
                {creatingProject ? "Creating..." : "Create project"}
              </button>
            </div>
          </div>
        )}

        <div className="new-run__grid">
          <label className="new-run__field">
            <span className="new-run__label">Use project</span>
            <select
              className="new-run__input"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
              disabled={projects.length === 0 || submitting}
              required
            >
              {projects.length === 0 && <option value="">No projects — create one above</option>}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <label className="new-run__field">
            <span className="new-run__label">Target URL</span>
            <input
              className="new-run__input"
              type="text"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="http://juice-shop:8000"
              disabled={submitting}
              required
            />
            <span className="new-run__hint">Must be reachable from the agent container.</span>
          </label>
        </div>
      </section>

      <section className="new-run__section new-run__section--placeholder">
        <h2 className="new-run__sec-title">Model · Crawler · Parallel · Agents</h2>
        <p className="new-run__placeholder">
          Inherited from project config. UI for per-run overrides arrives in Plan 4.
        </p>
      </section>

      {error && (
        <div className="new-run__error" role="alert">{error}</div>
      )}

      <footer className="new-run__foot">
        <button
          type="submit"
          className="new-run__submit"
          disabled={submitting || typeof projectId !== "number" || !target.trim()}
        >
          {submitting ? "Launching..." : "🚀 LAUNCH"}
        </button>
      </footer>
    </form>
  );
}
