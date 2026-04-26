import { useState } from "react";
import type { Project, ProjectUpdate } from "../../lib/api";
import { updateProject } from "../../lib/api";
import {
  ModelFields,
  AuthFields,
  CrawlerFields,
  ParallelFields,
  AgentsFields,
  JsonTextareaFields,
} from "./ProjectForms";
import "./ProjectEditModal.css";

type Tab = "model" | "auth" | "env" | "crawler" | "parallel" | "agents";

const TABS: { id: Tab; label: string }[] = [
  { id: "model", label: "Model" },
  { id: "auth", label: "Auth" },
  { id: "env", label: "Env" },
  { id: "crawler", label: "Crawler" },
  { id: "parallel", label: "Parallel" },
  { id: "agents", label: "Agents" },
];

type Props = {
  open: boolean;
  token: string;
  project: Project;
  onClose: () => void;
  onSaved: (updated: Project) => void;
};

export function ProjectEditModal({ open, token, project, onClose, onSaved }: Props) {
  const [tab, setTab] = useState<Tab>("model");
  const [draft, setDraft] = useState<ProjectUpdate>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const effective = { ...project, ...draft };

  function updateDraft(patch: ProjectUpdate) {
    setDraft(prev => ({ ...prev, ...patch }));
  }

  function handleSave() {
    setSaving(true);
    setError(null);
    void updateProject(token, project.id, draft).then(
      (updated) => {
        onSaved(updated);
        setDraft({});
        onClose();
        setSaving(false);
      },
      (e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setSaving(false);
      },
    );
  }

  return (
    <div className="pem-backdrop" role="dialog" aria-modal="true" aria-labelledby="pem-title">
      <div className="pem">
        <header className="pem__head">
          <h2 id="pem-title" className="pem__title">Edit Project — {project.name}</h2>
          <button type="button" className="pem__close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <nav className="pem__tabs" role="tablist">
          {TABS.map(t => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
              className={`pem__tab ${tab === t.id ? "pem__tab--active" : ""}`}
              onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>

        <div className="pem__body">
          {tab === "model" && (
            <ModelFields
              providerId={effective.provider_id}
              modelId={effective.model_id}
              smallModelId={effective.small_model_id}
              apiKey={effective.api_key ?? ""}
              baseUrl={effective.base_url}
              onChange={updateDraft}
            />
          )}
          {tab === "auth" && (
            <AuthFields value={effective.auth_json ?? ""}
              onChange={v => updateDraft({ auth_json: v })} />
          )}
          {tab === "env" && (
            <JsonTextareaFields value={effective.env_json ?? ""}
              onChange={v => updateDraft({ env_json: v })}
              label="Env JSON"
              placeholder='{"SOME_VAR": "value"}' />
          )}
          {tab === "crawler" && (
            <CrawlerFields value={effective.crawler_json}
              onChange={v => updateDraft({ crawler_json: v })} />
          )}
          {tab === "parallel" && (
            <ParallelFields value={effective.parallel_json}
              onChange={v => updateDraft({ parallel_json: v })} />
          )}
          {tab === "agents" && (
            <AgentsFields value={effective.agents_json}
              onChange={v => updateDraft({ agents_json: v })} />
          )}
        </div>

        {error && <p className="pem__error" role="alert">{error}</p>}

        <footer className="pem__foot">
          <button type="button" className="pem__cancel" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="pem__save" onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}
