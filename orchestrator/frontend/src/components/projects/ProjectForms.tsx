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

// ===== AUTH =====
export function AuthFields(props: { value: string; onChange: (v: string) => void }) {
  return <JsonTextareaFields value={props.value} onChange={props.onChange}
    label="Auth JSON"
    placeholder='{"cookies":{}, "headers":{}, "tokens":{}}'
  />;
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
