import type { Run } from "../../lib/api";

type SidebarProps = {
  runs: Run[];
  selectedRunId: number | null;
  onSelectRun: (projectId: number, runId: number) => void;
  onNewRun: () => void;
  username: string;
  onLogout: () => void;
  projectIdForRun: (run: Run) => number;
};

const STATUS_STATES = ["all", "active", "done", "failed"] as const;
type StatusFilter = (typeof STATUS_STATES)[number];

function runIsActive(run: Run): boolean {
  return !["completed", "failed", "error"].includes(run.status.toLowerCase());
}

function runStateClass(run: Run): "running" | "done" | "failed" | "queued" {
  const s = run.status.toLowerCase();
  if (s === "completed") return "done";
  if (s === "failed" || s === "error") return "failed";
  if (s === "queued" || s === "pending") return "queued";
  return "running";
}

export function Sidebar({
  runs, selectedRunId, onSelectRun, onNewRun, username, onLogout, projectIdForRun,
}: SidebarProps) {
  const filter: StatusFilter = "all"; // Filter UI placeholder — wired in a later plan
  const search: string = "";

  const visible = runs.filter((r) => {
    if (filter !== "all") {
      if (filter === "active" && !runIsActive(r)) return false;
      if (filter === "done" && r.status.toLowerCase() !== "completed") return false;
      if (filter === "failed" && !["failed", "error"].includes(r.status.toLowerCase())) return false;
    }
    if (search && !r.target.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <nav className="sidebar" aria-label="Runs">
      <header className="sidebar__head">
        <div className="sidebar__brand">RED<span>TEAM</span></div>
        <div className="sidebar__brand-sub">orchestrator · {runs.length} runs</div>
        <div className="sidebar__filters" role="tablist">
          {STATUS_STATES.map((s) => (
            <button
              key={s}
              className={`sidebar__filter ${s === filter ? "sidebar__filter--on" : ""}`}
              role="tab"
              aria-selected={s === filter}
              type="button"
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      <div className="sidebar__actions">
        <button className="sidebar__new-run" type="button" onClick={onNewRun}>
          + NEW RUN
        </button>
      </div>

      <ul className="sidebar__list">
        {visible.map((run) => {
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
                  updated {new Date(run.updated_at).toLocaleTimeString()}
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
