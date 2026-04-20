import type { Project, Run } from "../../lib/api";
import { parseServerTimestamp } from "../../lib/format";

type SidebarProps = {
  runs: Run[];
  selectedRunId: number | null;
  onSelectRun: (projectId: number, runId: number) => void;
  onNewRun: () => void;
  username: string;
  onLogout: () => void;
  projectIdForRun: (run: Run) => number;
  // NEW: project-level actions
  projects?: Project[];
  onEditProject?: (project: Project) => void;
  onDeleteProject?: (projectId: number) => void;
  onDeleteRun?: (projectId: number, runId: number) => void;
};

function runStateClass(run: Run): "running" | "done" | "failed" | "queued" | "stopped" {
  const s = run.status.toLowerCase();
  if (s === "completed") return "done";
  if (s === "failed" || s === "error") return "failed";
  if (s === "queued" || s === "pending") return "queued";
  if (s === "stopped") return "stopped";
  return "running";
}

export function Sidebar({
  runs, selectedRunId, onSelectRun, onNewRun, username, onLogout, projectIdForRun,
  projects = [], onEditProject, onDeleteProject, onDeleteRun,
}: SidebarProps) {
  // Build a map of projectId -> Project for header rendering
  const projectMap = new Map(projects.map((p) => [p.id, p]));

  // Group runs by projectId, preserving sorted order
  const grouped: { projectId: number; project: Project | undefined; runs: Run[] }[] = [];
  const seen = new Set<number>();
  for (const run of runs) {
    const pid = projectIdForRun(run);
    if (!seen.has(pid)) {
      seen.add(pid);
      grouped.push({ projectId: pid, project: projectMap.get(pid), runs: [] });
    }
    grouped.find((g) => g.projectId === pid)!.runs.push(run);
  }

  // Also add projects with no runs so their headers still appear for Edit/Delete
  for (const p of projects) {
    if (!seen.has(p.id)) {
      grouped.push({ projectId: p.id, project: p, runs: [] });
    }
  }

  const hasProjectActions = onEditProject || onDeleteProject || onDeleteRun;

  return (
    <nav className="sidebar" aria-label="Runs">
      <header className="sidebar__head">
        <div className="sidebar__brand">RED<span>TEAM</span></div>
        <div className="sidebar__brand-sub">orchestrator · {runs.length} runs</div>
      </header>

      <div className="sidebar__actions">
        <button className="sidebar__new-run" type="button" onClick={onNewRun}>
          + NEW RUN
        </button>
      </div>

      <ul className="sidebar__list">
        {hasProjectActions
          ? grouped.map(({ projectId, project, runs: groupRuns }) => (
              <li key={projectId} className="sidebar__project-group">
                {/* Project heading with Edit/Delete actions */}
                <header className="sidebar__project-head">
                  <span className="sidebar__project-name">
                    {project?.name ?? `Project #${projectId}`}
                  </span>
                  <div className="sidebar__project-actions">
                    {onEditProject && project && (
                      <button
                        type="button"
                        className="sidebar__action"
                        aria-label={`Edit project ${project.name}`}
                        onClick={(e) => { e.stopPropagation(); onEditProject(project); }}
                      >
                        ✎
                      </button>
                    )}
                    {onDeleteProject && project && (
                      <button
                        type="button"
                        className="sidebar__action sidebar__action--danger"
                        aria-label={`Delete project ${project.name}`}
                        onClick={(e) => { e.stopPropagation(); onDeleteProject(project.id); }}
                      >
                        🗑
                      </button>
                    )}
                  </div>
                </header>

                {/* Runs under this project */}
                <ul className="sidebar__run-list">
                  {groupRuns.map((run) => {
                    const stateClass = runStateClass(run);
                    const isSelected = run.id === selectedRunId;
                    return (
                      <li key={run.id} className="sidebar__run">
                        <button
                          type="button"
                          className={`sidebar__run-main sidebar__run--${stateClass} ${isSelected ? "sidebar__run--on" : ""}`}
                          onClick={() => onSelectRun(projectId, run.id)}
                          aria-current={isSelected ? "true" : undefined}
                        >
                          <div className="sidebar__run-top">
                            <span className="sidebar__run-dot" aria-hidden="true" />
                            <span className="sidebar__run-target">{run.target}</span>
                            <span className="sidebar__run-state">{run.status.toUpperCase()}</span>
                          </div>
                          <div className="sidebar__run-id">#r-{run.id}</div>
                          <time className="sidebar__run-meta" dateTime={run.updated_at}>
                            updated {parseServerTimestamp(run.updated_at)?.toLocaleTimeString() ?? "—"}
                          </time>
                        </button>
                        {onDeleteRun && (
                          <button
                            type="button"
                            className="sidebar__action sidebar__action--danger"
                            aria-label={`Delete run ${run.target}`}
                            onClick={(e) => { e.stopPropagation(); onDeleteRun(projectId, run.id); }}
                          >
                            🗑
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))
          : runs.map((run) => {
              // Legacy flat layout (no project actions wired) — unchanged appearance
              const stateClass = runStateClass(run);
              const isSelected = run.id === selectedRunId;
              return (
                <li key={run.id}>
                  <button
                    type="button"
                    className={`sidebar__run sidebar__run--${stateClass} ${isSelected ? "sidebar__run--on" : ""}`}
                    onClick={() => onSelectRun(projectIdForRun(run), run.id)}
                    aria-current={isSelected ? "true" : undefined}
                  >
                    <div className="sidebar__run-top">
                      <span className="sidebar__run-dot" aria-hidden="true" />
                      <span className="sidebar__run-target">{run.target}</span>
                      <span className="sidebar__run-state">{run.status.toUpperCase()}</span>
                    </div>
                    <div className="sidebar__run-id">#r-{run.id}</div>
                    <time className="sidebar__run-meta" dateTime={run.updated_at}>
                      updated {parseServerTimestamp(run.updated_at)?.toLocaleTimeString() ?? "—"}
                    </time>
                  </button>
                </li>
              );
            })}
      </ul>

      <footer className="sidebar__foot">
        <span className="sidebar__user">{username}</span>
        <button type="button" className="sidebar__logout" onClick={onLogout}>
          Logout
        </button>
      </footer>
    </nav>
  );
}
