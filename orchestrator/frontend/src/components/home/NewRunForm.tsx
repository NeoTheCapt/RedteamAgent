import { FormEvent, useState } from "react";
import type { Project } from "../../lib/api";
import "./NewRunForm.css";

type NewRunFormProps = {
  projects: Project[];
  onCreateRun: (projectId: number, target: string) => Promise<void>;
};

export function NewRunForm({ projects, onCreateRun }: NewRunFormProps) {
  const [projectId, setProjectId] = useState<number | "">(projects[0]?.id ?? "");
  const [target, setTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <h2 className="new-run__sec-title">Target</h2>
        <div className="new-run__grid">
          <label className="new-run__field">
            <span className="new-run__label">Project</span>
            <select
              className="new-run__input"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
              disabled={projects.length === 0 || submitting}
              required
            >
              {projects.length === 0 && <option value="">No projects — create one first</option>}
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
