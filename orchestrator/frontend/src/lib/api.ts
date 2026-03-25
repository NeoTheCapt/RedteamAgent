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
};

export type Run = {
  id: number;
  target: string;
  status: string;
  engagement_root: string;
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

const API_BASE = "";

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
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

export function createProject(token: string, name: string) {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
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

export function listEvents(token: string, projectId: number, runId: number) {
  return request<EventRecord[]>(`/projects/${projectId}/runs/${runId}/events`, {}, token);
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
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws/projects/${projectId}/runs/${runId}?ticket=${encodeURIComponent(ticket)}`;
}
