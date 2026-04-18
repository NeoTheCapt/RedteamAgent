export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: {
    id: number;
    username: string;
  };
};

export type Project = {
  id: number;
  name: string;
  slug: string;
  root_path: string;
  provider_id: string;
  model_id: string;
  small_model_id: string;
  base_url: string;
  api_key_configured: boolean;
  auth_configured: boolean;
  env_configured: boolean;
};

export type Run = {
  id: number;
  target: string;
  status: string;
  engagement_root: string;
  created_at: string;
  updated_at: string;
};

export type RunSummary = {
  target: {
    target: string;
    hostname: string;
    scheme: string;
    path: string;
    port: number;
    scope_entries: string[];
    engagement_dir: string;
    started_at: string;
    status: string;
  };
  overview: {
    findings_count: number;
    active_agents: number;
    available_agents: number;
    current_phase: string;
    updated_at: string;
  };
  runtime_model: {
    configured_provider: string;
    configured_model: string;
    configured_small_model: string;
    observed_provider: string;
    observed_model: string;
    status: string;
    summary: string;
  };
  coverage: {
    total_cases: number;
    completed_cases: number;
    pending_cases: number;
    processing_cases: number;
    error_cases: number;
    case_types: Array<{
      type: string;
      total?: number;
      done?: number;
      pending?: number;
      processing?: number;
      error?: number;
    }>;
    total_surfaces: number;
    remaining_surfaces: number;
    high_risk_remaining: number;
    surface_statuses: Record<string, number>;
    surface_types: Array<{
      type: string;
      count?: number;
    }>;
  };
  current: {
    phase: string;
    task_name: string;
    agent_name: string;
    summary: string;
  };
  phases: Array<{
    phase: string;
    label: string;
    state: string;
    task_events: number;
    active_agents: number;
    latest_summary: string;
  }>;
  agents: Array<{
    agent_name: string;
    phase: string;
    status: string;
    task_name: string;
    summary: string;
    updated_at: string;
  }>;
  dispatches: {
    total: number;
    active: number;
    done: number;
    failed: number;
  };
  cases: {
    total: number;
    done: number;
    running: number;
    queued: number;
    error: number;
    findings: number;
  };
};

export type EventRecord = {
  id: number;
  event_type: string;
  phase: string;
  task_name: string;
  agent_name: string;
  summary: string;
  created_at: string;
};

export type Artifact = {
  name: string;
  relative_path: string;
  media_type: string;
  sensitive: boolean;
  exists: boolean;
};

export type ArtifactContent = Artifact & {
  content: string;
};

export type WebSocketTicketResponse = {
  ticket: string;
};

export type ObservedPathRecord = {
  method: string;
  url: string;
  type: string;
  status: string;
  assigned_agent: string;
  source: string;
};

export type Dispatch = {
  id: string;
  phase: string;
  round: number;
  agent: string;
  slot: string;
  task: string | null;
  state: string;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
};

export type Case = {
  case_id: number;
  method: string;
  path: string;
  category: string | null;
  dispatch_id: string | null;
  state: string;
  result: string | null;
  finding_id: string | null;
  started_at: number | null;
  finished_at: number | null;
  duration_ms: number | null;
};

export type CaseListFilter = {
  state?: string;
  method?: string;
  category?: string;
};

export type DocumentEntry = {
  name: string;
  path: string;
  size: number;
  mtime: number;
};

export type DocumentTree = {
  findings: DocumentEntry[];
  reports: DocumentEntry[];
  intel: DocumentEntry[];
  surface: DocumentEntry[];
  other: DocumentEntry[];
};

export type DocumentContent = {
  path: string;
  content: string;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function appBaseUrl(): URL {
  const pathname = window.location.pathname.endsWith("/")
    ? window.location.pathname
    : `${window.location.pathname}/`;
  return new URL(pathname, window.location.origin);
}

function resolveAppUrl(path: string): string {
  const relativePath = path.replace(/^\/+/, "");
  return new URL(relativePath, appBaseUrl()).toString();
}

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `Request failed: ${response.status}`;
  }

  try {
    const payload = JSON.parse(text) as { detail?: unknown };
    if (Array.isArray(payload.detail) && payload.detail.length > 0) {
      const first = payload.detail[0] as { loc?: unknown[]; msg?: string };
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
      if (typeof field === "string" && typeof first.msg === "string") {
        return `${field}: ${first.msg}`;
      }
      if (typeof first.msg === "string") {
        return first.msg;
      }
    }
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall back to the raw body below.
  }

  return text;
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(resolveAppUrl(path), {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}

export function login(username: string, password: string) {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function register(username: string, password: string) {
  return request<{ id: number; username: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function listProjects(token: string) {
  return request<Project[]>("/projects", {}, token);
}

export type ProjectConfigInput = {
  provider_id?: string;
  model_id?: string;
  small_model_id?: string;
  api_key?: string;
  clear_api_key?: boolean;
  base_url?: string;
  auth_json?: string;
  clear_auth_json?: boolean;
  env_json?: string;
  clear_env_json?: boolean;
};

export function createProject(token: string, name: string, config: ProjectConfigInput = {}) {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, ...config }),
  }, token);
}

export function updateProject(token: string, projectId: number, config: ProjectConfigInput) {
  return request<Project>(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(config),
  }, token);
}

export function deleteProject(token: string, projectId: number) {
  return request<void>(`/projects/${projectId}`, {
    method: "DELETE",
  }, token);
}

export function listRuns(token: string, projectId: number) {
  return request<Run[]>(`/projects/${projectId}/runs`, {}, token);
}

export function createRun(token: string, projectId: number, target: string) {
  return request<Run>(`/projects/${projectId}/runs`, {
    method: "POST",
    body: JSON.stringify({ target }),
  }, token);
}

export function deleteRun(token: string, projectId: number, runId: number) {
  return request<void>(`/projects/${projectId}/runs/${runId}`, {
    method: "DELETE",
  }, token);
}

export function stopRun(token: string, projectId: number, runId: number): Promise<Run> {
  return request<Run>(
    `/projects/${projectId}/runs/${runId}/status`,
    { method: "POST", body: JSON.stringify({ status: "stopped" }) },
    token,
  );
}

export function listEvents(token: string, projectId: number, runId: number) {
  return request<EventRecord[]>(`/projects/${projectId}/runs/${runId}/events`, {}, token);
}

export function getRunSummary(token: string, projectId: number, runId: number) {
  return request<RunSummary>(`/projects/${projectId}/runs/${runId}/summary`, {}, token);
}

export function listObservedPaths(token: string, projectId: number, runId: number) {
  return request<ObservedPathRecord[]>(`/projects/${projectId}/runs/${runId}/observed-paths`, {}, token);
}

export function listArtifacts(token: string, projectId: number, runId: number) {
  return request<Artifact[]>(`/projects/${projectId}/runs/${runId}/artifacts`, {}, token);
}

export function readArtifact(token: string, projectId: number, runId: number, artifactName: string) {
  return request<ArtifactContent>(`/projects/${projectId}/runs/${runId}/artifacts/${artifactName}`, {}, token);
}

export function createWebSocketTicket(token: string) {
  return request<WebSocketTicketResponse>("/auth/ws-ticket", { method: "POST" }, token);
}

export function runWebSocketUrl(projectId: number, runId: number, ticket: string) {
  const httpUrl = new URL(
    `ws/projects/${projectId}/runs/${runId}?ticket=${encodeURIComponent(ticket)}`,
    appBaseUrl(),
  );
  httpUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return httpUrl.toString();
}

export function listDispatches(
  token: string,
  projectId: number,
  runId: number,
  phase?: string,
) {
  const query = phase ? `?phase=${encodeURIComponent(phase)}` : "";
  return request<Dispatch[]>(
    `/projects/${projectId}/runs/${runId}/dispatches${query}`,
    {},
    token,
  );
}

export function listCases(
  token: string,
  projectId: number,
  runId: number,
  filter: CaseListFilter = {},
) {
  const params = new URLSearchParams();
  if (filter.state) {
    params.set("state", filter.state);
  }
  if (filter.method) {
    params.set("method", filter.method);
  }
  if (filter.category) {
    params.set("category", filter.category);
  }
  const query = params.toString();
  const suffix = query ? `?${query}` : "";
  return request<Case[]>(
    `/projects/${projectId}/runs/${runId}/cases${suffix}`,
    {},
    token,
  );
}

export function getCase(
  token: string,
  projectId: number,
  runId: number,
  caseId: number,
) {
  return request<Case>(
    `/projects/${projectId}/runs/${runId}/cases/${caseId}`,
    {},
    token,
  );
}

export function listDocuments(token: string, projectId: number, runId: number) {
  return request<DocumentTree>(
    `/projects/${projectId}/runs/${runId}/documents`,
    {},
    token,
  );
}

export function getDocument(
  token: string,
  projectId: number,
  runId: number,
  path: string,
) {
  // Backend route is /documents/{path:path}; percent-encode each segment so
  // interior "/" separators are preserved for nested paths like
  // "runtime/process.log" while spaces / special chars are safely escaped.
  const encodedPath = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return request<DocumentContent>(
    `/projects/${projectId}/runs/${runId}/documents/${encodedPath}`,
    {},
    token,
  );
}
