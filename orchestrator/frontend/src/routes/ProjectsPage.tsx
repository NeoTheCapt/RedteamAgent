import { FormEvent, useMemo, useState } from "react";

import type { Project, ProjectConfigInput, Run } from "../lib/api";

type ProjectsPageProps = {
  username: string;
  projects: Project[];
  runsByProject: Record<number, Run[]>;
  onCreateProject: (name: string, config: ProjectConfigInput) => Promise<void>;
  onUpdateProject: (projectId: number, config: ProjectConfigInput) => Promise<void>;
  onCreateRun: (projectId: number, target: string) => Promise<void>;
  onDeleteProject: (projectId: number) => Promise<void>;
  onDeleteRun: (projectId: number, runId: number) => Promise<void>;
  onOpenRun: (projectId: number, runId: number) => void;
  onLogout: () => void;
};

type ProviderOption = {
  id: string;
  label: string;
  models: string[];
  smallModels: string[];
  apiKeyLabel: string;
  showBaseUrl?: boolean;
};

type ProjectConfigForm = {
  provider_id: string;
  model_id: string;
  small_model_id: string;
  api_key: string;
  base_url: string;
  bearer_token: string;
  session_cookie_name: string;
  session_cookie_value: string;
  extra_header_name: string;
  extra_header_value: string;
  http_proxy: string;
  https_proxy: string;
  no_proxy: string;
  katana_headless_options: string;
  clear_api_key?: boolean;
  clear_auth_json?: boolean;
  clear_env_json?: boolean;
};

const PROVIDERS: ProviderOption[] = [
  {
    id: "openai",
    label: "OpenAI",
    models: ["gpt-5.4", "gpt-5.4-mini", "gpt-5.3"],
    smallModels: ["gpt-5.4-mini", "gpt-5.3"],
    apiKeyLabel: "OpenAI API key",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    models: ["claude-sonnet-4-5", "claude-opus-4-1"],
    smallModels: ["claude-3-5-haiku"],
    apiKeyLabel: "Anthropic API key",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    models: ["openai/gpt-5.4", "openai/gpt-5.4-mini", "anthropic/claude-sonnet-4-5"],
    smallModels: ["openai/gpt-5.4-mini", "anthropic/claude-3-5-haiku"],
    apiKeyLabel: "OpenRouter API key",
  },
  {
    id: "openai-compatible",
    label: "OpenAI-Compatible",
    models: ["gpt-5.4", "gpt-5.4-mini", "llama-3.3-70b-instruct"],
    smallModels: ["gpt-5.4-mini", "llama-3.1-8b-instruct"],
    apiKeyLabel: "Compatible API key",
    showBaseUrl: true,
  },
];

const DEFAULT_KATANA_HEADLESS =
  "--no-sandbox,--disable-dev-shm-usage,--disable-gpu";

function emptyProjectForm(): ProjectConfigForm {
  return {
    provider_id: "openai",
    model_id: "gpt-5.4",
    small_model_id: "gpt-5.4-mini",
    api_key: "",
    base_url: "",
    bearer_token: "",
    session_cookie_name: "session",
    session_cookie_value: "",
    extra_header_name: "",
    extra_header_value: "",
    http_proxy: "",
    https_proxy: "",
    no_proxy: "",
    katana_headless_options: DEFAULT_KATANA_HEADLESS,
  };
}

function parseJsonObject(raw: string): Record<string, unknown> {
  if (!raw.trim()) {
    return {};
  }
  try {
    const payload = JSON.parse(raw);
    return payload && typeof payload === "object" && !Array.isArray(payload) ? (payload as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function formFromProject(project?: Project, current?: ProjectConfigInput): ProjectConfigForm {
  const authPayload = parseJsonObject((current?.auth_json as string | undefined) ?? "");
  const envPayload = parseJsonObject((current?.env_json as string | undefined) ?? "");
  const headers = authPayload.headers && typeof authPayload.headers === "object" ? (authPayload.headers as Record<string, unknown>) : {};
  const cookies = authPayload.cookies && typeof authPayload.cookies === "object" ? (authPayload.cookies as Record<string, unknown>) : {};

  const authorizationHeader =
    typeof headers.Authorization === "string" && headers.Authorization.startsWith("Bearer ")
      ? headers.Authorization.slice("Bearer ".length)
      : "";

  const extraHeaderEntry = Object.entries(headers).find(([key]) => key !== "Authorization");
  const cookieEntry = Object.entries(cookies)[0];

  const providerId = current?.provider_id ?? project?.provider_id ?? "openai";
  const provider = PROVIDERS.find((item) => item.id === providerId) ?? PROVIDERS[0];

  return {
    provider_id: provider.id,
    model_id: current?.model_id ?? project?.model_id ?? provider.models[0] ?? "",
    small_model_id: current?.small_model_id ?? project?.small_model_id ?? provider.smallModels[0] ?? "",
    api_key: current?.api_key ?? "",
    base_url: current?.base_url ?? project?.base_url ?? "",
    bearer_token: authorizationHeader,
    session_cookie_name: typeof cookieEntry?.[0] === "string" ? cookieEntry[0] : "session",
    session_cookie_value: typeof cookieEntry?.[1] === "string" ? cookieEntry[1] : "",
    extra_header_name: typeof extraHeaderEntry?.[0] === "string" ? extraHeaderEntry[0] : "",
    extra_header_value: typeof extraHeaderEntry?.[1] === "string" ? extraHeaderEntry[1] : "",
    http_proxy: typeof envPayload.HTTP_PROXY === "string" ? envPayload.HTTP_PROXY : "",
    https_proxy: typeof envPayload.HTTPS_PROXY === "string" ? envPayload.HTTPS_PROXY : "",
    no_proxy: typeof envPayload.NO_PROXY === "string" ? envPayload.NO_PROXY : "",
    katana_headless_options:
      typeof envPayload.KATANA_HEADLESS_OPTIONS === "string"
        ? envPayload.KATANA_HEADLESS_OPTIONS
        : DEFAULT_KATANA_HEADLESS,
    clear_api_key: current?.clear_api_key ?? false,
    clear_auth_json: current?.clear_auth_json ?? false,
    clear_env_json: current?.clear_env_json ?? false,
  };
}

function providerFor(providerId: string): ProviderOption {
  return PROVIDERS.find((provider) => provider.id === providerId) ?? PROVIDERS[0];
}

function normalizeModelChoice(providerId: string, value: string, kind: "model" | "small"): string {
  const provider = providerFor(providerId);
  const options = kind === "model" ? provider.models : provider.smallModels;
  if (options.includes(value)) {
    return value;
  }
  return options[0] ?? "";
}

function toProjectConfigInput(form: ProjectConfigForm): ProjectConfigInput {
  const headers: Record<string, string> = {};
  const cookies: Record<string, string> = {};
  const env: Record<string, string> = {};

  if (form.bearer_token.trim()) {
    headers.Authorization = `Bearer ${form.bearer_token.trim()}`;
  }
  if (form.extra_header_name.trim() && form.extra_header_value.trim()) {
    headers[form.extra_header_name.trim()] = form.extra_header_value.trim();
  }
  if (form.session_cookie_name.trim() && form.session_cookie_value.trim()) {
    cookies[form.session_cookie_name.trim()] = form.session_cookie_value.trim();
  }
  if (form.http_proxy.trim()) {
    env.HTTP_PROXY = form.http_proxy.trim();
  }
  if (form.https_proxy.trim()) {
    env.HTTPS_PROXY = form.https_proxy.trim();
  }
  if (form.no_proxy.trim()) {
    env.NO_PROXY = form.no_proxy.trim();
  }
  if (form.katana_headless_options.trim() && form.katana_headless_options.trim() !== DEFAULT_KATANA_HEADLESS) {
    env.KATANA_HEADLESS_OPTIONS = form.katana_headless_options.trim();
  }

  return {
    provider_id: form.provider_id,
    model_id: form.model_id,
    small_model_id: form.small_model_id,
    api_key: form.api_key,
    clear_api_key: form.clear_api_key,
    base_url: form.base_url.trim(),
    auth_json: Object.keys(headers).length || Object.keys(cookies).length ? JSON.stringify({ headers, cookies }) : "",
    clear_auth_json: form.clear_auth_json,
    env_json: Object.keys(env).length ? JSON.stringify(env) : "",
    clear_env_json: form.clear_env_json,
  };
}

function updateProvider(form: ProjectConfigForm, providerId: string): ProjectConfigForm {
  const provider = providerFor(providerId);
  return {
    ...form,
    provider_id: provider.id,
    model_id: normalizeModelChoice(provider.id, form.model_id, "model"),
    small_model_id: normalizeModelChoice(provider.id, form.small_model_id, "small"),
    base_url: provider.showBaseUrl ? form.base_url : "",
  };
}

function ProjectConfigEditor({
  form,
  setForm,
  configured,
  submitLabel,
  disabled,
}: {
  form: ProjectConfigForm;
  setForm: (updater: (current: ProjectConfigForm) => ProjectConfigForm) => void;
  configured?: { apiKey: boolean; auth: boolean; env: boolean };
  submitLabel: string;
  disabled: boolean;
}) {
  const provider = providerFor(form.provider_id);

  return (
    <>
      <div className="field-grid">
        <label className="field">
          <span>Model provider</span>
          <select
            value={form.provider_id}
            onChange={(event) => setForm((current) => updateProvider(current, event.target.value))}
          >
            {PROVIDERS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Primary model</span>
          <select
            value={form.model_id}
            onChange={(event) => setForm((current) => ({ ...current, model_id: event.target.value }))}
          >
            {provider.models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Small model</span>
          <select
            value={form.small_model_id}
            onChange={(event) => setForm((current) => ({ ...current, small_model_id: event.target.value }))}
          >
            {provider.smallModels.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="field-grid">
        <label className="field">
          <span>{provider.apiKeyLabel}</span>
          <input
            placeholder={configured?.apiKey ? "Stored; enter a new key to replace" : "Paste API key"}
            value={form.api_key}
            onChange={(event) =>
              setForm((current) => ({ ...current, api_key: event.target.value, clear_api_key: false }))
            }
            type="password"
          />
        </label>
        {provider.showBaseUrl ? (
          <label className="field">
            <span>Provider base URL</span>
            <input
              placeholder="https://your-gateway.example/v1"
              value={form.base_url}
              onChange={(event) => setForm((current) => ({ ...current, base_url: event.target.value }))}
            />
          </label>
        ) : null}
      </div>

      <section className="config-group">
        <div className="panel-header">
          <div>
            <h3>Session credentials</h3>
            <p className="meta-text">Optional authenticated context for the run.</p>
          </div>
        </div>
        <div className="field-grid">
          <label className="field">
            <span>Bearer token</span>
            <input
              placeholder="Paste bearer token"
              value={form.bearer_token}
              onChange={(event) =>
                setForm((current) => ({ ...current, bearer_token: event.target.value, clear_auth_json: false }))
              }
              type="password"
            />
          </label>
          <label className="field">
            <span>Session cookie name</span>
            <input
              placeholder="session"
              value={form.session_cookie_name}
              onChange={(event) =>
                setForm((current) => ({ ...current, session_cookie_name: event.target.value, clear_auth_json: false }))
              }
            />
          </label>
          <label className="field">
            <span>Session cookie value</span>
            <input
              placeholder="Paste cookie value"
              value={form.session_cookie_value}
              onChange={(event) =>
                setForm((current) => ({ ...current, session_cookie_value: event.target.value, clear_auth_json: false }))
              }
              type="password"
            />
          </label>
          <label className="field">
            <span>Extra header name</span>
            <input
              placeholder="X-Api-Key"
              value={form.extra_header_name}
              onChange={(event) =>
                setForm((current) => ({ ...current, extra_header_name: event.target.value, clear_auth_json: false }))
              }
            />
          </label>
          <label className="field">
            <span>Extra header value</span>
            <input
              placeholder="Header value"
              value={form.extra_header_value}
              onChange={(event) =>
                setForm((current) => ({ ...current, extra_header_value: event.target.value, clear_auth_json: false }))
              }
              type="password"
            />
          </label>
        </div>
        {configured?.auth ? (
          <label className="field-inline">
            <input
              type="checkbox"
              checked={Boolean(form.clear_auth_json)}
              onChange={(event) =>
                setForm((current) => ({ ...current, clear_auth_json: event.target.checked }))
              }
            />
            <span>Clear stored session credentials</span>
          </label>
        ) : null}
      </section>

      <section className="config-group">
        <div className="panel-header">
          <div>
            <h3>All-in-one runtime settings</h3>
            <p className="meta-text">Common networking and browser controls for the container.</p>
          </div>
        </div>
        <div className="field-grid">
          <label className="field">
            <span>HTTP proxy</span>
            <input
              placeholder="http://proxy.example:8080"
              value={form.http_proxy}
              onChange={(event) =>
                setForm((current) => ({ ...current, http_proxy: event.target.value, clear_env_json: false }))
              }
            />
          </label>
          <label className="field">
            <span>HTTPS proxy</span>
            <input
              placeholder="http://proxy.example:8080"
              value={form.https_proxy}
              onChange={(event) =>
                setForm((current) => ({ ...current, https_proxy: event.target.value, clear_env_json: false }))
              }
            />
          </label>
          <label className="field">
            <span>No proxy</span>
            <input
              placeholder="127.0.0.1,localhost,.internal"
              value={form.no_proxy}
              onChange={(event) =>
                setForm((current) => ({ ...current, no_proxy: event.target.value, clear_env_json: false }))
              }
            />
          </label>
          <label className="field field-span-full">
            <span>Katana headless options</span>
            <input
              placeholder={DEFAULT_KATANA_HEADLESS}
              value={form.katana_headless_options}
              onChange={(event) =>
                setForm((current) => ({ ...current, katana_headless_options: event.target.value, clear_env_json: false }))
              }
            />
          </label>
        </div>
        {configured?.env ? (
          <label className="field-inline">
            <input
              type="checkbox"
              checked={Boolean(form.clear_env_json)}
              onChange={(event) =>
                setForm((current) => ({ ...current, clear_env_json: event.target.checked }))
              }
            />
            <span>Clear stored runtime settings</span>
          </label>
        ) : null}
      </section>

      {configured?.apiKey ? (
        <label className="field-inline">
          <input
            type="checkbox"
            checked={Boolean(form.clear_api_key)}
            onChange={(event) =>
              setForm((current) => ({ ...current, clear_api_key: event.target.checked }))
            }
          />
          <span>Clear stored API key</span>
        </label>
      ) : null}

      <button type="submit" className="secondary-button" disabled={disabled}>
        {submitLabel}
      </button>
    </>
  );
}

export function ProjectsPage({
  username,
  projects,
  runsByProject,
  onCreateProject,
  onUpdateProject,
  onCreateRun,
  onDeleteProject,
  onDeleteRun,
  onOpenRun,
  onLogout,
}: ProjectsPageProps) {
  const [projectName, setProjectName] = useState("");
  const [projectConfig, setProjectConfig] = useState<ProjectConfigForm>(emptyProjectForm);
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [runTargets, setRunTargets] = useState<Record<number, string>>({});
  const [creatingRunId, setCreatingRunId] = useState<number | null>(null);
  const [settingsByProject, setSettingsByProject] = useState<Record<number, ProjectConfigForm>>({});
  const [savingProjectId, setSavingProjectId] = useState<number | null>(null);

  const totalRuns = useMemo(
    () => Object.values(runsByProject).reduce((count, runs) => count + runs.length, 0),
    [runsByProject],
  );

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingProject(true);
    setProjectError(null);
    try {
      await onCreateProject(projectName, toProjectConfigInput(projectConfig));
      setProjectName("");
      setProjectConfig(emptyProjectForm());
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleUpdateProjectSettings(event: FormEvent<HTMLFormElement>, project: Project) {
    event.preventDefault();
    setSavingProjectId(project.id);
    try {
      const form = settingsByProject[project.id] ?? formFromProject(project);
      await onUpdateProject(project.id, toProjectConfigInput(form));
      setSettingsByProject((current) => ({
        ...current,
        [project.id]: {
          ...form,
          api_key: "",
        },
      }));
    } finally {
      setSavingProjectId(null);
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
            <ProjectConfigEditor
              form={projectConfig}
              setForm={(updater) => setProjectConfig((current) => updater(current))}
              submitLabel={creatingProject ? "Creating..." : "Create project"}
              disabled={creatingProject}
            />
            {projectError ? <p className="error-text">{projectError}</p> : null}
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
              <form className="stack" onSubmit={(event) => void handleUpdateProjectSettings(event, project)}>
                <ProjectConfigEditor
                  form={settingsByProject[project.id] ?? formFromProject(project)}
                  setForm={(updater) =>
                    setSettingsByProject((current) => ({
                      ...current,
                      [project.id]: updater(current[project.id] ?? formFromProject(project)),
                    }))
                  }
                  configured={{
                    apiKey: project.api_key_configured,
                    auth: project.auth_configured,
                    env: project.env_configured,
                  }}
                  submitLabel={savingProjectId === project.id ? "Saving..." : "Save project settings"}
                  disabled={savingProjectId === project.id}
                />
              </form>

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
