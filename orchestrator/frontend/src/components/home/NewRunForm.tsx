import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Project, ProjectInput } from "../../lib/api";
import { ModelFields } from "../projects/ProjectForms";
import "./NewRunForm.css";

type NewRunFormProps = {
  projects: Project[];
  onCreateRun: (projectId: number, target: string) => Promise<void>;
  onCreateProject: (input: ProjectInput) => Promise<void>;
  onEditProject: (project: Project) => void;
};

// ===== Summarizer helpers =====

function summarizeCrawler(json: string): string {
  try {
    const obj = JSON.parse(json || "{}");
    const keys = Object.keys(obj);
    return keys.length === 0 ? "(defaults)" : `${keys.length} override${keys.length > 1 ? "s" : ""}`;
  } catch {
    return "(invalid)";
  }
}

function summarizeParallel(json: string): string {
  try {
    const obj = JSON.parse(json || "{}");
    const n = (obj as Record<string, unknown>).REDTEAM_MAX_PARALLEL_BATCHES;
    return n != null ? `max ${n} batches` : "(defaults)";
  } catch {
    return "(invalid)";
  }
}

function summarizeAgents(json: string): string {
  try {
    const obj = JSON.parse(json || "{}") as Record<string, unknown>;
    const disabled = Object.entries(obj).filter(([, v]) => v === false).map(([k]) => k);
    if (disabled.length === 0) return "all enabled";
    return `${disabled.length} disabled: ${disabled.slice(0, 2).join(", ")}${disabled.length > 2 ? "\u2026" : ""}`;
  } catch {
    return "(invalid)";
  }
}

export function NewRunForm({ projects, onCreateRun, onCreateProject, onEditProject }: NewRunFormProps) {
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

  // Advanced model fields for new project creation.
  const [newProjectProvider, setNewProjectProvider] = useState("");
  const [newProjectModelId, setNewProjectModelId] = useState("");
  const [newProjectSmallModelId, setNewProjectSmallModelId] = useState("");
  const [newProjectApiKey, setNewProjectApiKey] = useState("");
  const [newProjectBaseUrl, setNewProjectBaseUrl] = useState("");

  // The currently selected project object (for inherited summary).
  const selectedProject = useMemo(
    () => (typeof projectId === "number" ? projects.find(p => p.id === projectId) ?? null : null),
    [projectId, projects],
  );

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
      const input: ProjectInput = { name };
      if (newProjectProvider) input.provider_id = newProjectProvider;
      if (newProjectModelId) input.model_id = newProjectModelId.trim();
      if (newProjectSmallModelId) input.small_model_id = newProjectSmallModelId.trim();
      if (newProjectApiKey) input.api_key = newProjectApiKey;
      if (newProjectBaseUrl) input.base_url = newProjectBaseUrl.trim();
      await onCreateProject(input);
      setNewProjectName("");
      setNewProjectProvider("");
      setNewProjectModelId("");
      setNewProjectSmallModelId("");
      setNewProjectApiKey("");
      setNewProjectBaseUrl("");
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
          Select a project and a target URL. Agent and crawler config is inherited
          from the project.
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
            </label>

            <details className="new-run__advanced">
              <summary className="new-run__advanced-toggle">Advanced (optional)</summary>
              <p className="new-run__advanced-hint">
                Configure model now, or leave empty and edit the project later.
              </p>
              <ModelFields
                providerId={newProjectProvider}
                modelId={newProjectModelId}
                smallModelId={newProjectSmallModelId}
                apiKey={newProjectApiKey}
                baseUrl={newProjectBaseUrl}
                onChange={(patch) => {
                  if (patch.provider_id !== undefined) setNewProjectProvider(patch.provider_id);
                  if (patch.model_id !== undefined) setNewProjectModelId(patch.model_id);
                  if (patch.small_model_id !== undefined) setNewProjectSmallModelId(patch.small_model_id);
                  if (patch.api_key !== undefined) setNewProjectApiKey(patch.api_key);
                  if (patch.base_url !== undefined) setNewProjectBaseUrl(patch.base_url);
                }}
              />
            </details>

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

      {selectedProject && (
        <section className="new-run__section new-run__section--inherited">
          <h2 className="new-run__sec-title">Inherited from project</h2>
          <dl className="new-run__inherited">
            <div className="new-run__inherited-row">
              <dt>Model</dt>
              <dd>{selectedProject.model_id || "(using .env default)"}</dd>
            </div>
            <div className="new-run__inherited-row">
              <dt>Crawler</dt>
              <dd>{summarizeCrawler(selectedProject.crawler_json)}</dd>
            </div>
            <div className="new-run__inherited-row">
              <dt>Parallel</dt>
              <dd>{summarizeParallel(selectedProject.parallel_json)}</dd>
            </div>
            <div className="new-run__inherited-row">
              <dt>Agents</dt>
              <dd>{summarizeAgents(selectedProject.agents_json)}</dd>
            </div>
          </dl>
          <button
            type="button"
            className="new-run__edit-project"
            onClick={() => onEditProject(selectedProject)}
          >
            Edit project configuration
          </button>
        </section>
      )}

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
