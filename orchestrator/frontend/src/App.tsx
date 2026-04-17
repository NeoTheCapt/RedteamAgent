import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createProject,
  createRun,
  listProjects,
  listRuns,
  login,
  register,
} from "./lib/api";
import type { Project, Run } from "./lib/api";
import { LoginPage } from "./routes/LoginPage";
import { ShellPage } from "./routes/ShellPage";

type SessionState = {
  token: string;
  username: string;
};

const SESSION_STORAGE_KEY = "redteam-orchestrator-session";

function navigate(route: string) {
  window.location.hash = route;
}

export default function App() {
  const [session, setSession] = useState<SessionState | null>(() => {
    try {
      const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.token === "string" && typeof parsed.username === "string") {
        return parsed as SessionState;
      }
      return null;
    } catch {
      // Mangled localStorage entry — log and start fresh rather than white-screen.
      console.warn("Invalid session payload; clearing.");
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [runsByProject, setRunsByProject] = useState<Record<number, Run[]>>({});

  const expireSession = useCallback(() => {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    setSession(null);
    setProjects([]);
    setRunsByProject({});
    navigate("/");
  }, []);

  useEffect(() => {
    if (!session) {
      setProjects([]);
      setRunsByProject({});
      return;
    }

    let cancelled = false;
    const token = session.token;

    async function tick() {
      try {
        const nextProjects = await listProjects(token);
        if (cancelled) return;
        setProjects(nextProjects);
        const entries = await Promise.all(
          nextProjects.map(
            async (project) => [project.id, await listRuns(token, project.id)] as const,
          ),
        );
        if (cancelled) return;
        setRunsByProject(Object.fromEntries(entries));
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) {
          expireSession();
          return;
        }
        throw error;
      }
    }

    void tick();
    const interval = window.setInterval(() => {
      void tick();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [session, expireSession]);

  async function handleLogin(username: string, password: string) {
    const response = await login(username, password);
    const nextSession = {
      token: response.access_token,
      username: response.user.username,
    };
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
    navigate("/");
  }

  async function handleRegister(username: string, password: string) {
    await register(username, password);
    await handleLogin(username, password);
  }

  async function handleCreateRun(projectId: number, target: string) {
    if (!session) return;
    const run = await createRun(session.token, projectId, target);
    setRunsByProject((current) => ({
      ...current,
      [projectId]: [...(current[projectId] ?? []), run],
    }));
    navigate(`/projects/${projectId}/runs/${run.id}/dashboard`);
  }

  const handleCreateProject = useCallback(async (name: string) => {
    if (!session) return;
    try {
      await createProject(session.token, name);
      // Refresh projects so the new one appears in the sidebar + dropdown.
      const nextProjects = await listProjects(session.token);
      setProjects(nextProjects);
      const entries = await Promise.all(
        nextProjects.map(
          async (project) => [project.id, await listRuns(session.token, project.id)] as const,
        ),
      );
      setRunsByProject(Object.fromEntries(entries));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        expireSession();
        return;
      }
      throw err;
    }
  }, [session, expireSession]);

  if (!session) {
    return <LoginPage onLogin={handleLogin} onRegister={handleRegister} />;
  }

  return (
    <ShellPage
      token={session.token}
      username={session.username}
      projects={projects}
      runsByProject={runsByProject}
      onLogout={expireSession}
      onCreateRun={handleCreateRun}
      onCreateProject={handleCreateProject}
    />
  );
}
