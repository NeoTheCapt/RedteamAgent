import { useEffect, useMemo, useState } from "react";
import { Sidebar } from "../components/shell/Sidebar";
import { RunPanel } from "../components/shell/RunPanel";
import { TabNav, type TabId } from "../components/shell/TabNav";
import { EmptyTab } from "../components/shell/EmptyTab";
import { DashboardTab } from "../components/dashboard/DashboardTab";
import { NewRunForm } from "../components/home/NewRunForm";
import type { Project, Run, RunSummary } from "../lib/api";
import { getRunSummary } from "../lib/api";

type ShellPageProps = {
  token: string;
  username: string;
  projects: Project[];
  runsByProject: Record<number, Run[]>;
  onLogout: () => void;
  onRefreshProjects: () => Promise<void>;
  onCreateRun: (projectId: number, target: string) => Promise<void>;
};

type Route =
  | { kind: "home" }
  | { kind: "run"; projectId: number; runId: number; tab: TabId };

function parseRoute(hash: string): Route {
  const h = hash.replace(/^#/, "");
  const match = h.match(/^\/projects\/(\d+)\/runs\/(\d+)(?:\/(\w+))?$/);
  if (match) {
    const tab = (match[3] ?? "dashboard") as TabId;
    return { kind: "run", projectId: Number(match[1]), runId: Number(match[2]), tab };
  }
  return { kind: "home" };
}

function navigate(route: string) {
  window.location.hash = route;
}

export function ShellPage(props: ShellPageProps) {
  const { token, username, projects, runsByProject, onLogout, onCreateRun } = props;
  const [route, setRoute] = useState<Route>(parseRoute(window.location.hash));
  const [summary, setSummary] = useState<RunSummary | null>(null);

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
  const routeTab = route.kind === "run" ? route.tab : null;

  useEffect(() => {
    if (!selected) {
      setSummary(null);
      return;
    }
    let cancelled = false;
    getRunSummary(token, selected.__projectId, selected.id)
      .then((s) => { if (!cancelled) setSummary(s); })
      .catch(() => { if (!cancelled) setSummary(null); });
    return () => { cancelled = true; };
  }, [token, runKey, routeTab]);

  const runtimeLabel = selected && summary
    ? `updated ${new Date(summary.overview.updated_at).toLocaleTimeString()}`
    : undefined;

  const tabCounts: Partial<Record<TabId, number | string>> | undefined = summary
    ? {
        cases: summary.cases.total || undefined,
        events: "live",
      }
    : undefined;

  function renderTab(tab: TabId) {
    if (!selected || !summary) return <EmptyTab label="Loading run..." note="Fetching summary data." />;
    switch (tab) {
      case "dashboard":
        return <DashboardTab summary={summary} />;
      case "progress":
        return <EmptyTab label="Progress" note="Kanban view arrives in Plan 3." />;
      case "cases":
        return <EmptyTab label="Cases" note="Case explorer arrives in Plan 3." />;
      case "documents":
        return <EmptyTab label="Documents" note="Document browser arrives in Plan 4." />;
      case "events":
        return <EmptyTab label="Events" note="Live event stream arrives in Plan 4." />;
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
        />
      </aside>
      <main className="shell__main">
        {route.kind === "home" && (
          <div style={{ padding: "var(--sp-6)", overflowY: "auto" }}>
            <NewRunForm projects={projects} onCreateRun={onCreateRun} />
          </div>
        )}
        {route.kind === "run" && selected && (
          <RunPanel
            run={selected}
            runtimeLabel={runtimeLabel}
            currentPhase={summary?.overview.current_phase}
            onStop={undefined}
          >
            <TabNav
              current={route.tab}
              counts={tabCounts}
              onSelect={(tab) =>
                navigate(`/projects/${route.projectId}/runs/${route.runId}/${tab}`)
              }
            />
            <div className="tab-content">{renderTab(route.tab)}</div>
          </RunPanel>
        )}
        {route.kind === "run" && !selected && (
          <EmptyTab
            label="Run not found"
            note={`No run #${route.runId} in project #${route.projectId}. It may have been deleted.`}
          />
        )}
      </main>
    </div>
  );
}
