import { useState, useEffect } from "react";

// ===== MODEL =====
type ModelFieldsProps = {
  providerId: string;
  modelId: string;
  smallModelId: string;
  apiKey: string;
  baseUrl: string;
  onChange: (patch: Partial<{
    provider_id: string; model_id: string; small_model_id: string;
    api_key: string; base_url: string;
  }>) => void;
};

const PROVIDER_OPTIONS = [
  { value: "", label: "(unset)" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "openai-compatible", label: "OpenAI-compatible (custom)" },
];

export function ModelFields(props: ModelFieldsProps) {
  return (
    <div className="pforms">
      <label className="pforms__field">
        <span className="pforms__label">Provider</span>
        <select className="pforms__input" value={props.providerId}
          onChange={e => props.onChange({ provider_id: e.target.value })}>
          {PROVIDER_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>
      <label className="pforms__field">
        <span className="pforms__label">Model ID</span>
        <input className="pforms__input" type="text" value={props.modelId}
          onChange={e => props.onChange({ model_id: e.target.value })}
          placeholder="e.g. gpt-4o / claude-sonnet-4-5 / deepseek/deepseek-r1" />
      </label>
      <label className="pforms__field">
        <span className="pforms__label">Small Model</span>
        <input className="pforms__input" type="text" value={props.smallModelId}
          onChange={e => props.onChange({ small_model_id: e.target.value })}
          placeholder="(optional) faster/cheaper model for summaries" />
      </label>
      <label className="pforms__field">
        <span className="pforms__label">API Key</span>
        <input className="pforms__input" type="password" value={props.apiKey}
          onChange={e => props.onChange({ api_key: e.target.value })}
          placeholder="Leave empty to keep stored key" autoComplete="off" />
      </label>
      <label className="pforms__field">
        <span className="pforms__label">Base URL</span>
        <input className="pforms__input" type="text" value={props.baseUrl}
          onChange={e => props.onChange({ base_url: e.target.value })}
          placeholder="(optional) https://gateway.example/v1" />
      </label>
    </div>
  );
}

// ===== JSON TEXTAREA (shared) =====
type JsonTextareaFieldsProps = {
  value: string;          // JSON string
  onChange: (next: string) => void;
  label: string;
  placeholder?: string;
  rows?: number;
};

export function JsonTextareaFields({ value, onChange, label, placeholder, rows = 8 }: JsonTextareaFieldsProps) {
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setDraft(value); }, [value]);

  function handleChange(next: string) {
    setDraft(next);
    if (next.trim() === "") {
      setError(null);
      onChange(next);
      return;
    }
    try {
      JSON.parse(next);
      setError(null);
      onChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid JSON");
    }
  }

  return (
    <div className="pforms">
      <label className="pforms__field pforms__field--grow">
        <span className="pforms__label">{label}</span>
        <textarea className="pforms__input pforms__textarea" value={draft} rows={rows}
          onChange={e => handleChange(e.target.value)} placeholder={placeholder}
          aria-invalid={error ? "true" : undefined} />
      </label>
      {error && <p className="pforms__error" role="alert">Invalid JSON: {error}</p>}
    </div>
  );
}

// ===== SCHEMA-AWARE JSON EDITOR (Auth + Env) =====
// Dedicated editors for the two free-form JSON tabs so they get more than
// "is it valid JSON?" — both have a shape contract on the server (see
// orchestrator/backend/app/services/projects.py validate_auth_json /
// validate_env_json) and the frontend should mirror that contract so users
// don't only learn about it via a 400 on Save. Both editors:
//   1. expose a populated example block (real cookie pair, real env var),
//   2. validate the full schema inline and surface a precise error,
//   3. propagate validity up via onValidityChange so the modal can disable
//      Save while the textarea is in a broken state.

type ValidationResult =
  | { ok: true; normalized: string }
  | { ok: false; error: string };

function describeType(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v;
}

export function validateAuthJson(value: string): ValidationResult {
  const raw = value.trim();
  if (!raw) return { ok: true, normalized: "" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    return { ok: false, error: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: "Auth must be a JSON object" };
  }
  const obj = parsed as Record<string, unknown>;
  for (const key of ["cookies", "headers", "tokens"] as const) {
    if (!(key in obj)) continue;
    const sub = obj[key];
    if (typeof sub !== "object" || sub === null || Array.isArray(sub)) {
      return { ok: false, error: `auth.${key} must be a JSON object of strings (got ${describeType(sub)})` };
    }
    for (const [k, v] of Object.entries(sub as Record<string, unknown>)) {
      if (typeof v !== "string") {
        return { ok: false, error: `auth.${key}.${k} must be a string (got ${describeType(v)})` };
      }
    }
  }
  for (const key of ["discovered_credentials", "validated_credentials", "credentials"] as const) {
    if (key in obj && !Array.isArray(obj[key])) {
      return { ok: false, error: `auth.${key} must be a JSON array (got ${describeType(obj[key])})` };
    }
  }
  return { ok: true, normalized: raw };
}

const ENV_KEY_RE = /^[A-Z_][A-Z0-9_]*$/;
const RESERVED_ENV_KEYS = new Set([
  "ORCHESTRATOR_BASE_URL",
  "ORCHESTRATOR_TOKEN",
  "ORCHESTRATOR_PROJECT_ID",
  "ORCHESTRATOR_RUN_ID",
  "OPENCODE_HOME",
]);

export function validateEnvJson(value: string): ValidationResult {
  const raw = value.trim();
  if (!raw) return { ok: true, normalized: "" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    return { ok: false, error: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: "Env must be a JSON object" };
  }
  const obj = parsed as Record<string, unknown>;
  for (const [key, val] of Object.entries(obj)) {
    if (!ENV_KEY_RE.test(key)) {
      return { ok: false, error: `Env key '${key}' must match [A-Z_][A-Z0-9_]* (POSIX env-var convention)` };
    }
    if (RESERVED_ENV_KEYS.has(key)) {
      return { ok: false, error: `Env key '${key}' is reserved by the orchestrator and cannot be overridden` };
    }
    if (typeof val !== "string" && typeof val !== "number" && typeof val !== "boolean") {
      return { ok: false, error: `Env '${key}' value must be string/number/bool (got ${describeType(val)})` };
    }
  }
  return { ok: true, normalized: raw };
}

type SchemaEditorProps = {
  value: string;
  onChange: (next: string) => void;
  onValidityChange?: (valid: boolean) => void;
  label: string;
  hint: string;
  example: string;
  validate: (raw: string) => ValidationResult;
  testId?: string;
};

function SchemaEditor({ value, onChange, onValidityChange, label, hint, example, validate, testId }: SchemaEditorProps) {
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value);
    const r = validate(value);
    setError(r.ok ? null : r.error);
    onValidityChange?.(r.ok);
    // Re-syncing on parent value change only — validate / onValidityChange are
    // stable references in practice and including them here would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function handleChange(next: string) {
    setDraft(next);
    const r = validate(next);
    if (r.ok) {
      setError(null);
      onChange(r.normalized);
      onValidityChange?.(true);
    } else {
      setError(r.error);
      onValidityChange?.(false);
    }
  }

  return (
    <div className="pforms">
      <label className="pforms__field pforms__field--grow">
        <span className="pforms__label">{label}</span>
        <textarea
          className="pforms__input pforms__textarea"
          value={draft}
          rows={8}
          onChange={e => handleChange(e.target.value)}
          aria-invalid={error ? "true" : undefined}
          data-testid={testId}
        />
      </label>
      {error && <p className="pforms__error" role="alert">{error}</p>}
      <p className="pforms__hint">{hint}</p>
      <details className="pforms__example">
        <summary>Example</summary>
        <pre className="pforms__example-code">{example}</pre>
      </details>
    </div>
  );
}

const AUTH_EXAMPLE = `{
  "cookies": { "session": "abc123" },
  "headers": { "Authorization": "Bearer eyJhbGc..." },
  "tokens":  { "csrf": "xyz789" }
}`;

const ENV_EXAMPLE = `{
  "HTTP_PROXY": "http://proxy.lab:8080",
  "MY_TARGET_USER": "alice",
  "CAPTCHA_SOLVER_KEY": "k-12345"
}`;

type EditorProps = {
  value: string;
  onChange: (v: string) => void;
  onValidityChange?: (valid: boolean) => void;
};

export function AuthFields({ value, onChange, onValidityChange }: EditorProps) {
  return (
    <SchemaEditor
      value={value}
      onChange={onChange}
      onValidityChange={onValidityChange}
      label="Auth JSON"
      hint="Written verbatim to the engagement's auth.json. cookies/headers/tokens become Record<string,string>; the agent uses them for every authenticated request. Discovered/validated credentials are arrays."
      example={AUTH_EXAMPLE}
      validate={validateAuthJson}
      testId="auth-json-editor"
    />
  );
}

export function EnvFields({ value, onChange, onValidityChange }: EditorProps) {
  return (
    <SchemaEditor
      value={value}
      onChange={onChange}
      onValidityChange={onValidityChange}
      label="Env JSON"
      hint="Forwarded to the run container as -e KEY=VALUE flags. Keys must match POSIX env-var convention (UPPER_SNAKE_CASE). Values are coerced to strings. ORCHESTRATOR_* keys are reserved."
      example={ENV_EXAMPLE}
      validate={validateEnvJson}
      testId="env-json-editor"
    />
  );
}

// ===== CRAWLER =====
type CrawlerFieldsProps = {
  value: string;  // JSON string
  onChange: (next: string) => void;
};

const CRAWLER_NUMERIC_KEYS = [
  { key: "KATANA_CRAWL_DEPTH", label: "Crawl Depth", placeholder: "8" },
  { key: "KATANA_TIMEOUT_SECONDS", label: "Timeout (sec)", placeholder: "20" },
  { key: "KATANA_CONCURRENCY", label: "Concurrency", placeholder: "15" },
  { key: "KATANA_PARALLELISM", label: "Parallelism", placeholder: "4" },
  { key: "KATANA_RATE_LIMIT", label: "Rate Limit (req/s)", placeholder: "60" },
];

const CRAWLER_BOOLEAN_KEYS = [
  { key: "KATANA_ENABLE_HYBRID", label: "Hybrid mode (headless + static)" },
  { key: "KATANA_ENABLE_XHR", label: "XHR extraction" },
  { key: "KATANA_ENABLE_HEADLESS", label: "Headless browser" },
  { key: "KATANA_ENABLE_JSLUICE", label: "JSLuice (JS analysis)" },
  { key: "KATANA_ENABLE_PATH_CLIMB", label: "Path climbing" },
];

export function CrawlerFields({ value, onChange }: CrawlerFieldsProps) {
  const [data, setData] = useState<Record<string, unknown>>(() => {
    try { return JSON.parse(value || "{}") || {}; } catch { return {}; }
  });

  useEffect(() => {
    try { setData(JSON.parse(value || "{}") || {}); } catch { setData({}); }
  }, [value]);

  function patch(key: string, v: unknown) {
    const next = { ...data };
    if (v === "" || v === undefined) delete next[key];
    else next[key] = v;
    setData(next);
    onChange(JSON.stringify(next));
  }

  return (
    <div className="pforms">
      {CRAWLER_NUMERIC_KEYS.map(({ key, label, placeholder }) => (
        <label key={key} className="pforms__field">
          <span className="pforms__label">{label}</span>
          <input className="pforms__input" type="number"
            value={(data[key] as string | number | undefined) ?? ""}
            onChange={e => patch(key, e.target.value === "" ? "" : Number(e.target.value))}
            placeholder={placeholder} />
        </label>
      ))}
      <label className="pforms__field">
        <span className="pforms__label">Crawl Duration</span>
        <input className="pforms__input" type="text"
          value={(data.KATANA_CRAWL_DURATION as string) ?? ""}
          onChange={e => patch("KATANA_CRAWL_DURATION", e.target.value)}
          placeholder="15m" />
      </label>
      <label className="pforms__field">
        <span className="pforms__label">Strategy</span>
        <select className="pforms__input"
          value={(data.KATANA_STRATEGY as string) ?? ""}
          onChange={e => patch("KATANA_STRATEGY", e.target.value)}>
          <option value="">(default)</option>
          <option value="breadth-first">breadth-first</option>
          <option value="depth-first">depth-first</option>
        </select>
      </label>
      {CRAWLER_BOOLEAN_KEYS.map(({ key, label }) => (
        <label key={key} className="pforms__field pforms__field--checkbox">
          <input type="checkbox"
            checked={data[key] === 1 || data[key] === "1" || data[key] === true}
            onChange={e => patch(key, e.target.checked ? 1 : 0)} />
          <span className="pforms__label-inline">{label}</span>
        </label>
      ))}
    </div>
  );
}

// ===== PARALLEL =====
export function ParallelFields({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [data, setData] = useState<Record<string, unknown>>(() => {
    try { return JSON.parse(value || "{}") || {}; } catch { return {}; }
  });

  useEffect(() => {
    try { setData(JSON.parse(value || "{}") || {}); } catch { setData({}); }
  }, [value]);

  function patch(key: string, v: unknown) {
    const next = { ...data };
    if (v === "" || v === undefined) delete next[key];
    else next[key] = v;
    setData(next);
    onChange(JSON.stringify(next));
  }

  return (
    <div className="pforms">
      <label className="pforms__field">
        <span className="pforms__label">Max Parallel Batches</span>
        <input className="pforms__input" type="number"
          value={(data.REDTEAM_MAX_PARALLEL_BATCHES as string | number | undefined) ?? ""}
          onChange={e => patch("REDTEAM_MAX_PARALLEL_BATCHES", e.target.value === "" ? "" : Number(e.target.value))}
          placeholder="3 (default)" min={1} max={32} />
      </label>
    </div>
  );
}

// ===== AGENTS =====
const AGENT_IDS = [
  "recon-specialist",
  "source-analyzer",
  "vulnerability-analyst",
  "exploit-developer",
  "fuzzer",
  "osint-analyst",
  "report-writer",
] as const;

export function AgentsFields({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [data, setData] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(value || "{}") || {}; } catch { return {}; }
  });

  useEffect(() => {
    try { setData(JSON.parse(value || "{}") || {}); } catch { setData({}); }
  }, [value]);

  function toggle(agent: string, enabled: boolean) {
    const next = { ...data };
    if (enabled) {
      // Default is enabled — represent "enabled" by removing from the map.
      delete next[agent];
    } else {
      next[agent] = false;
    }
    setData(next);
    onChange(JSON.stringify(next));
  }

  return (
    <div className="pforms">
      <p className="pforms__hint">All agents are enabled by default. Uncheck to disable for this project.</p>
      {AGENT_IDS.map(agent => {
        const isDisabled = data[agent] === false;
        return (
          <label key={agent} className="pforms__field pforms__field--checkbox">
            <input type="checkbox" checked={!isDisabled}
              onChange={e => toggle(agent, e.target.checked)} />
            <span className="pforms__label-inline">{agent}</span>
          </label>
        );
      })}
    </div>
  );
}
