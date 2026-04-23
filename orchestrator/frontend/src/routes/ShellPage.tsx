import { useEffect, useMemo, useRef, useState } from "react";
import { Sidebar } from "../components/shell/Sidebar";
import { RunPanel } from "../components/shell/RunPanel";
import { TabNav, type TabId } from "../components/shell/TabNav";
import { EmptyTab } from "../components/shell/EmptyTab";
import { ConfirmDialog } from "../components/shell/ConfirmDialog";
import { DashboardTab } from "../components/dashboard/DashboardTab";
import { ProgressTab } from "../components/progress/ProgressTab";
import { CasesTab } from "../components/cases/CasesTab";
import { DocumentsTab } from "../components/documents/DocumentsTab";
import { EventsTab } from "../components/events/EventsTab";
import { NewRunForm } from "../components/home/NewRunForm";
import { ProjectEditModal } from "../components/projects/ProjectEditModal";
import type { Project, ProjectInput, Run, RunSummary } from "../lib/api";
import { getRunSummary, stopRun } from "../lib/api";
import { parseServerTimestamp } from "../lib/format";

type ShellPageProps = {
  token: string;
  username: string;
  projects: Project[];
  runsByProject: Record<number, Run[]>;
  onLogout: () => void;
  onCreateRun: (projectId: number, target: string) => Promise<void>;
  onCreateProject: (input: ProjectInput) => Promise<void>;
  onRefreshProjects?: () => Promise<void>;
  onDeleteProject?: (projectId: number) => Promise<void>;
  onDeleteRun?: (projectId: number, runId: number) => Promise<void>;
};

type DeleteTarget =
  | { kind: "project"; id: number; name: string }
  | { kind: "run"; projectId: number; runId: number; target: string };

type Route =
  | { kind: "home" }
  | { kind: "run"; projectId: number; runId: number; tab: TabId };

const VALID_TABS: readonly TabId[] = ["dashboard", "progress", "cases", "documents", "events"] as const;

function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  // Split off query string first, then normalize trailing slash on the path.
  const qIdx = raw.indexOf("?");
  const pathOnlyRaw = qIdx < 0 ? raw : raw.slice(0, qIdx);
  const pathOnly = pathOnlyRaw.replace(/\/$/, "");
  const match = pathOnly.match(/^\/projects\/(\d+)\/runs\/(\d+)(?:\/([\w-]+))?$/);
  if (match) {
    const rawTab = match[3];
    const tab: TabId = rawTab && (VALID_TABS as readonly string[]).includes(rawTab)
      ? (rawTab as TabId)
      : "dashboard";
    return { kind: "run", projectId: Number(match[1]), runId: Number(match[2]), tab };
  }
  return { kind: "home" };
}

function navigate(route: string) {
  window.location.hash = route;
}

export function ShellPage(props: ShellPageProps) {
  const {
    token, username, projects, runsByProject, onLogout,
    onCreateRun, onCreateProject, onRefreshProjects,
    onDeleteProject, onDeleteRun,
  } = props;
  const [route, setRoute] = useState<Route>(parseRoute(window.location.hash));
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    const handler = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  // Flatten runs + attach projectId
  const allRuns = useMemo(() => {
    const result: (Run & { __projectId: number })[] = [];
    for (const p of projects) {
      for (const r of runsByProject[p.id] ?? []) {
        result.push({ ...r, __projectId: p.id });
      }
    }
    result.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return result;
  }, [projects, runsByProject]);

  const selected =
    route.kind === "run"
      ? allRuns.find((r) => r.id === route.runId && r.__projectId === route.projectId) ?? null
      : null;

  const runKey = selected ? `${selected.__projectId}:${selected.id}` : null;
  const prevRunKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!selected) {
      setSummary(null);
      setSummaryError(null);
      prevRunKeyRef.current = null;
      return;
    }
    // If this is a DIFFERENT run than last time, clear summary immediately so
    // the previous run's data doesn't persist until the new run's first fetch.
    if (prevRunKeyRef.current !== runKey) {
      setSummary(null);
      setSummaryError(null);
    }
    prevRunKeyRef.current = runKey;

    let cancelled = false;
    const currentRun = selected;

    async function tick() {
      try {
        const s = await getRunSummary(token, currentRun.__projectId, currentRun.id);
        if (!cancelled) {
          setSummary(s);
          setSummaryError(null);
        }
      } catch (err) {
        // Transient fetch errors: keep the last known summary so the dashboard
        // doesn't flash to "Loading..." on a blip. Only the very first load
        // failure clears the panel, and only because we never had data.
        if (!cancelled) {
          setSummary((prev) => (prev ? prev : null));
          setSummaryError(err instanceof Error ? err.message : "refresh failed");
        }
        console.warn("summary fetch failed:", err);
      }
    }

    void tick();
    const interval = window.setInterval(() => { void tick(); }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [token, runKey]);

  const runtimeLabel = (() => {
    if (!selected || !summary) return undefined;
    const parsed = parseServerTimestamp(summary.overview.updated_at);
    if (!parsed) return "not yet updated";
    return `updated ${parsed.toLocaleTimeString()}`;
  })();

  const tabCounts: Partial<Record<TabId, number | string>> | undefined = summary
    ? {
        progress: summary.dispatches.active || undefined,
        cases: summary.cases.total || undefined,
        events: "live",
      }
    : undefined;

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      if (deleteTarget.kind === "project" && onDeleteProject) {
        await onDeleteProject(deleteTarget.id);
      } else if (deleteTarget.kind === "run" && onDeleteRun) {
        await onDeleteRun(deleteTarget.projectId, deleteTarget.runId);
        // If user was viewing the deleted run, navigate home
        if (
          route.kind === "run" &&
          route.runId === deleteTarget.runId &&
          route.projectId === deleteTarget.projectId
        ) {
          navigate("/");
        }
      }
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  async function handleStop(projectId: number, runId: number) {
    try {
      await stopRun(token, projectId, runId);
      // Optimistic refetch — the sidebar polls every 5s anyway.
    } catch (err) {
      console.warn("stop failed:", err);
    }
  }

  function renderTab(tab: TabId) {
    if (!selected || !summary) return <EmptyTab label="Loading run..." note="Fetching summary data." />;
    switch (tab) {
      case "dashboard":
        return (
          <DashboardTab
            token={token}
            projectId={selected.__projectId}
            runId={selected.id}
            summary={summary}
          />
        );
      case "progress":
        return (
          <ProgressTab
            token={token}
            projectId={selected.__projectId}
            runId={selected.id}
            currentPhase={summary.overview.current_phase ?? null}
            summary={summary}
          />
        );
      case "cases":
        return (
          <CasesTab
            token={token}
            projectId={selected.__projectId}
            runId={selected.id}
          />
        );
      case "documents":
        return <DocumentsTab token={token} projectId={selected.__projectId} runId={selected.id} />;
      case "events":
        return <EventsTab token={token} projectId={selected.__projectId} runId={selected.id} />;
    }
  }

  return (
    <div className="shell">
      <aside className="shell__side">
        <Sidebar
          runs={allRuns}
          selectedRunId={selected?.id ?? null}
          onSelectRun={(pid, rid) => navigate(`/projects/${pid}/runs/${rid}/dashboard`)}
          onNewRun={() => navigate("/")}
          username={username}
          onLogout={onLogout}
          projectIdForRun={(r) => (r as Run & { __projectId: number }).__projectId}
          projects={projects}
          onEditProject={(p) => setEditingProject(p)}
          onDeleteProject={onDeleteProject ? (id) => {
            const p = projects.find((proj) => proj.id === id);
            if (p) setDeleteTarget({ kind: "project", id, name: p.name });
          } : undefined}
          onDeleteRun={onDeleteRun ? (pid, rid) => {
            const run = allRuns.find((r) => r.id === rid);
            if (run) setDeleteTarget({ kind: "run", projectId: pid, runId: rid, target: run.target ?? `#${rid}` });
          } : undefined}
        />
      </aside>
      <main className="shell__main">
        {route.kind === "home" && (
          <div style={{ padding: "var(--sp-6)", overflowY: "auto" }}>
            <NewRunForm
              projects={projects}
              onCreateRun={onCreateRun}
              onCreateProject={onCreateProject}
              onEditProject={(p) => setEditingProject(p)}
            />
          </div>
        )}
        {route.kind === "run" && selected && (
          <RunPanel
            run={selected}
            runtimeLabel={runtimeLabel}
            currentPhase={summary?.overview.current_phase ?? null}
            onStop={() => void handleStop(selected.__projectId, selected.id)}
          >
            {summaryError && summary && (
              <div className="run-panel__alert" role="alert">
                Summary refresh failed — showing last known state · {summaryError}
              </div>
            )}
            <TabNav
              current={route.tab}
              counts={tabCounts}
              onSelect={(tab) =>
                navigate(`/projects/${route.projectId}/runs/${route.runId}/${tab}`)
              }
            />
            <div
              className="tab-content"
              role="tabpanel"
              id={`tabpanel-${route.tab}`}
              aria-labelledby={`tab-${route.tab}`}
            >
              {renderTab(route.tab)}
            </div>
          </RunPanel>
        )}
        {route.kind === "run" && !selected && (
          <EmptyTab
            label="Run not found"
            note={`No run #${route.runId} in project #${route.projectId}. It may have been deleted.`}
          />
        )}
      </main>
      {editingProject && (
        <ProjectEditModal
          open={true}
          token={token}
          project={editingProject}
          onClose={() => setEditingProject(null)}
          onSaved={() => {
            setEditingProject(null);
            if (onRefreshProjects) void onRefreshProjects();
          }}
        />
      )}
      <ConfirmDialog
        open={deleteTarget !== null}
        destructive
        title={deleteTarget?.kind === "project" ? "Delete project?" : "Delete run?"}
        message={
          deleteTarget?.kind === "project"
            ? `Deleting project "${deleteTarget.name}" removes its engagement data and stops any active runs. This cannot be undone.${deleteError ? `\n\nError: ${deleteError}` : ""}`
            : deleteTarget?.kind === "run"
            ? `Deleting run #${deleteTarget.runId} (target: ${deleteTarget.target}) removes its engagement files. This cannot be undone.${deleteError ? `\n\nError: ${deleteError}` : ""}`
            : ""
        }
        confirmLabel={deleting ? "Deleting…" : "Delete"}
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => { setDeleteTarget(null); setDeleteError(null); }}
      />
    </div>
  );
}
