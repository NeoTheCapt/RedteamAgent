import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Sidebar } from "../components/shell/Sidebar";
import type { Project, Run } from "../lib/api";

function mkRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1, target: "http://example.test", status: "running",
    engagement_root: "/x", created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
    ...overrides,
  } as Run;
}

function mkProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    name: "demo",
    description: null,
    scope: null,
    target_config: null,
    rules_of_engagement: null,
    created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
    ...overrides,
  } as Project;
}

// Default props helper to avoid repetition
function defaultProps(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  return {
    runs: [],
    selectedRunId: null,
    onSelectRun: vi.fn(),
    onNewRun: vi.fn(),
    username: "u",
    onLogout: vi.fn(),
    projectIdForRun: () => 1,
    ...overrides,
  };
}

describe("Sidebar", () => {
  it("renders runs with target, status, id", () => {
    const runs = [mkRun({ id: 1, target: "juice-shop:8000", status: "running" })];
    render(<Sidebar {...defaultProps({ runs })} />);
    expect(screen.getByText("juice-shop:8000")).toBeInTheDocument();
    expect(screen.getByText("#r-1")).toBeInTheDocument();
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
  });

  it("highlights the selected run via aria-current", () => {
    const runs = [
      mkRun({ id: 1, target: "a" }),
      mkRun({ id: 2, target: "b" }),
    ];
    render(<Sidebar {...defaultProps({ runs, selectedRunId: 2 })} />);
    const buttons = screen.getAllByRole("button");
    const bBtn = buttons.find((b) => b.textContent?.includes("b"));
    expect(bBtn).toHaveAttribute("aria-current", "true");
  });

  it("fires onSelectRun with projectId when a run is clicked", async () => {
    const onSelect = vi.fn();
    const runs = [mkRun({ id: 42, target: "x" })];
    render(<Sidebar {...defaultProps({ runs, onSelectRun: onSelect, projectIdForRun: () => 7 })} />);
    await userEvent.click(screen.getByText("x"));
    expect(onSelect).toHaveBeenCalledWith(7, 42);
  });

  it("fires onNewRun when + NEW RUN is clicked", async () => {
    const onNew = vi.fn();
    render(<Sidebar {...defaultProps({ onNewRun: onNew })} />);
    await userEvent.click(screen.getByText("+ NEW RUN"));
    expect(onNew).toHaveBeenCalled();
  });

  it("renders SQLite-format updated_at without Invalid Date (Bug 5)", () => {
    // SQLite timestamps are "YYYY-MM-DD HH:MM:SS" (no T, no TZ).
    // Safari's new Date() returns Invalid Date for that format.
    // parseServerTimestamp coerces it to a valid UTC Date.
    const runs = [mkRun({ updated_at: "2026-04-17 12:34:56" })];
    render(<Sidebar {...defaultProps({ runs })} />);
    const timeEl = document.querySelector("time");
    expect(timeEl?.textContent).not.toContain("Invalid Date");
    // The timestamp is valid, so it should render a real time (not the fallback "—").
    expect(timeEl?.textContent).toMatch(/^updated \d/);
  });

  // ── Project-level Edit / Delete actions ──────────────────────────────────

  it("invokes onEditProject when a project's Edit action is clicked", async () => {
    const onEditProject = vi.fn();
    const project = mkProject({ id: 1, name: "demo" });
    render(
      <Sidebar
        {...defaultProps({
          projects: [project],
          onEditProject,
          onDeleteProject: vi.fn(),
          onDeleteRun: vi.fn(),
        })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /edit project demo/i }));
    expect(onEditProject).toHaveBeenCalledWith(project);
  });

  it("invokes onDeleteProject when a project's Delete action is clicked", async () => {
    const onDeleteProject = vi.fn();
    const project = mkProject({ id: 42, name: "test" });
    render(
      <Sidebar
        {...defaultProps({
          projects: [project],
          onEditProject: vi.fn(),
          onDeleteProject,
          onDeleteRun: vi.fn(),
        })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /delete project test/i }));
    expect(onDeleteProject).toHaveBeenCalledWith(42);
  });

  it("invokes onDeleteRun when a run's delete icon is clicked", async () => {
    const onDeleteRun = vi.fn();
    const project = mkProject({ id: 1, name: "proj" });
    const run = mkRun({ id: 99, target: "http://ex.test", status: "running" });
    render(
      <Sidebar
        {...defaultProps({
          runs: [run],
          projects: [project],
          onEditProject: vi.fn(),
          onDeleteProject: vi.fn(),
          onDeleteRun,
          projectIdForRun: () => 1,
        })}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /delete run http:\/\/ex\.test/i }),
    );
    expect(onDeleteRun).toHaveBeenCalledWith(1, 99);
  });

  it("does not render Edit/Delete buttons when action handlers are omitted", () => {
    const project = mkProject({ id: 1, name: "silent" });
    render(<Sidebar {...defaultProps({ projects: [project] })} />);
    expect(screen.queryByRole("button", { name: /edit project/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /delete project/i })).toBeNull();
  });

  it("clicking a run's Delete button does not also trigger onSelectRun", async () => {
    const onSelectRun = vi.fn();
    const onDeleteRun = vi.fn();
    const project = mkProject({ id: 1, name: "proj" });
    const run = mkRun({ id: 5, target: "http://target.test" });
    render(
      <Sidebar
        {...defaultProps({
          runs: [run],
          projects: [project],
          onSelectRun,
          onEditProject: vi.fn(),
          onDeleteProject: vi.fn(),
          onDeleteRun,
          projectIdForRun: () => 1,
        })}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /delete run http:\/\/target\.test/i }),
    );
    expect(onDeleteRun).toHaveBeenCalledWith(1, 5);
    expect(onSelectRun).not.toHaveBeenCalled();
  });
});
