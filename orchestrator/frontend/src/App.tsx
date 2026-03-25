import { useEffect, useMemo, useState } from "react";

import { createProject, createRun, listProjects, listRuns, login, register } from "./lib/api";
import type { Project, Run } from "./lib/api";
import { LoginPage } from "./routes/LoginPage";
import { ProjectsPage } from "./routes/ProjectsPage";
import { RunPage } from "./routes/RunPage";

type SessionState = {
  token: string;
  username: string;
};

type RunRoute = {
  projectId: number;
  runId: number;
};

const SESSION_STORAGE_KEY = "redteam-orchestrator-session";

function currentRoute(): string {
  const hashRoute = window.location.hash.replace(/^#/, "");
  return hashRoute || "/projects";
}

function parseRunRoute(route: string): RunRoute | null {
  const match = route.match(/^\/projects\/(\d+)\/runs\/(\d+)$/);
  if (!match) {
    return null;
  }
  return { projectId: Number(match[1]), runId: Number(match[2]) };
}

function navigate(route: string) {
  window.location.hash = route;
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(() => {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SessionState) : null;
  });
  const [route, setRoute] = useState(currentRoute());
  const [projects, setProjects] = useState<Project[]>([]);
  const [runsByProject, setRunsByProject] = useState<Record<number, Run[]>>({});

  useEffect(() => {
    const handler = () => setRoute(currentRoute());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  useEffect(() => {
    if (!session) {
      setProjects([]);
      setRunsByProject({});
      return;
    }

    listProjects(session.token).then(async (nextProjects) => {
      setProjects(nextProjects);
      const entries = await Promise.all(
        nextProjects.map(async (project) => [project.id, await listRuns(session.token, project.id)] as const),
      );
      setRunsByProject(Object.fromEntries(entries));
    });
  }, [session]);

  const runRoute = useMemo(() => parseRunRoute(route), [route]);

  async function handleLogin(username: string, password: string) {
    const response = await login(username, password);
    const nextSession = {
      token: response.access_token,
      username: response.user.username,
    };
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
    navigate("/projects");
  }

  async function handleRegister(username: string, password: string) {
    await register(username, password);
    await handleLogin(username, password);
  }

  async function handleCreateProject(name: string) {
    if (!session) return;
    const project = await createProject(session.token, name);
    setProjects((current) => [...current, project]);
    setRunsByProject((current) => ({ ...current, [project.id]: [] }));
  }

  async function handleCreateRun(projectId: number, target: string) {
    if (!session) return;
    const run = await createRun(session.token, projectId, target);
    setRunsByProject((current) => ({
      ...current,
      [projectId]: [...(current[projectId] ?? []), run],
    }));
    navigate(`/projects/${projectId}/runs/${run.id}`);
  }

  function handleLogout() {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    setSession(null);
    navigate("/login");
  }

  if (!session) {
    return <LoginPage onLogin={handleLogin} onRegister={handleRegister} />;
  }

  if (runRoute) {
    return (
      <RunPage
        token={session.token}
        projectId={runRoute.projectId}
        runId={runRoute.runId}
        onBack={() => navigate("/projects")}
      />
    );
  }

  return (
    <ProjectsPage
      username={session.username}
      projects={projects}
      runsByProject={runsByProject}
      onCreateProject={handleCreateProject}
      onCreateRun={handleCreateRun}
      onOpenRun={(projectId, runId) => navigate(`/projects/${projectId}/runs/${runId}`)}
      onLogout={handleLogout}
    />
  );
}
