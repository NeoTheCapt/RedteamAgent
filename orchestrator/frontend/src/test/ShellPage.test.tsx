/**
 * ShellPage unit tests — focused on the stale-summary-on-run-switch bug (Bug 1).
 *
 * We mock all heavy sub-components and api calls so this test is fast and
 * doesn't depend on WebSocket or network.
 */
import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { RunSummary } from "../lib/api";

// ── Mock all components that have external side-effects ────────────────────
vi.mock("../components/shell/Sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));
vi.mock("../components/shell/RunPanel", () => ({
  RunPanel: ({ children, onStop }: { children: React.ReactNode; onStop?: () => void | Promise<void> }) => (
    <div data-testid="run-panel">
      {onStop ? <button onClick={() => void onStop()}>STOP</button> : null}
      {children}
    </div>
  ),
}));
vi.mock("../components/shell/TabNav", () => ({
  TabNav: () => <div data-testid="tab-nav" />,
}));
vi.mock("../components/shell/EmptyTab", () => ({
  EmptyTab: ({ label }: { label: string }) => <div data-testid="empty-tab">{label}</div>,
}));
vi.mock("../components/dashboard/DashboardTab", () => ({
  DashboardTab: ({ summary }: { summary: RunSummary }) => (
    <div data-testid="dashboard-tab">{summary.target.target}</div>
  ),
}));
vi.mock("../components/progress/ProgressTab", () => ({
  ProgressTab: () => <div data-testid="progress-tab" />,
}));
vi.mock("../components/cases/CasesTab", () => ({
  CasesTab: () => <div data-testid="cases-tab" />,
}));
vi.mock("../components/documents/DocumentsTab", () => ({
  DocumentsTab: () => <div data-testid="documents-tab" />,
}));
vi.mock("../components/events/EventsTab", () => ({
  EventsTab: () => <div data-testid="events-tab" />,
}));
vi.mock("../components/home/NewRunForm", () => ({
  NewRunForm: () => <div data-testid="new-run-form" />,
}));

// ── Mock API ───────────────────────────────────────────────────────────────
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    getRunSummary: vi.fn(),
    stopRun: vi.fn().mockResolvedValue(undefined),
  };
});
import { getRunSummary, stopRun } from "../lib/api";
const mockGetRunSummary = getRunSummary as unknown as ReturnType<typeof vi.fn>;
const mockStopRun = stopRun as unknown as ReturnType<typeof vi.fn>;

// ── Import component under test (after mocks) ──────────────────────────────
import { ShellPage } from "../routes/ShellPage";
import type { Project, Run } from "../lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────
function mkProject(id: number, name = `P${id}`): Project {
  return {
    id, name, slug: `p${id}`, root_path: "/x",
    provider_id: "", model_id: "", small_model_id: "", base_url: "",
    api_key_configured: false, auth_configured: false, env_configured: false,
    crawler_json: "{}", parallel_json: "{}", agents_json: "{}",
  };
}

function mkRun(id: number): Run {
  return {
    id, target: `http://run${id}.test`, status: "running",
    engagement_root: `/e${id}`,
    created_at: "2026-04-17T00:00:00Z",
    updated_at: "2026-04-17T00:00:00Z",
  };
}

function mkSummary(target: string): RunSummary {
  return {
    target: {
      target, hostname: "x", scheme: "http", path: "/", port: 80,
      scope_entries: [], engagement_dir: "/e", started_at: "2026-04-17T00:00:00Z",
      status: "running",
    },
    overview: {
      findings_count: 0, active_agents: 0, available_agents: 0,
      current_phase: "recon", updated_at: "2026-04-17T00:00:00Z",
    },
    runtime_model: {
      configured_provider: "", configured_model: "", configured_small_model: "",
      observed_provider: "", observed_model: "", status: "", summary: "",
    },
    coverage: {
      total_cases: 0, completed_cases: 0, pending_cases: 0,
      processing_cases: 0, error_cases: 0, case_types: [],
      total_surfaces: 0, remaining_surfaces: 0, high_risk_remaining: 0,
      surface_statuses: {}, surface_types: [],
    },
    current: { phase: "", task_name: "", agent_name: "", summary: "" },
    phases: [],
    agents: [],
    dispatches: { total: 0, active: 0, done: 0, failed: 0 },
    cases: { total: 0, done: 0, running: 0, queued: 0, error: 0, findings: 0 },
  };
}

function defaultProps(overrides: Partial<Parameters<typeof ShellPage>[0]> = {}) {
  return {
    token: "tok",
    username: "admin",
    projects: [mkProject(1), mkProject(2)],
    runsByProject: {
      1: [mkRun(10)],
      2: [mkRun(20)],
    },
    onLogout: vi.fn(),
    onCreateRun: vi.fn().mockResolvedValue(undefined),
    onCreateProject: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

// Hash-based routing helpers
function setHash(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

beforeEach(() => {
  window.location.hash = "";
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  window.location.hash = "";
});

describe("ShellPage — stale summary on run switch (Bug 1)", () => {
  it("clears summary immediately when switching to a different run", async () => {
    // Run 10 resolves with summary-A; run 20 will be controlled.
    let resolveRunB!: (v: RunSummary) => void;
    const runBPromise = new Promise<RunSummary>((resolve) => { resolveRunB = resolve; });

    mockGetRunSummary
      .mockResolvedValueOnce(mkSummary("http://run10.test"))  // run 10, first fetch
      .mockReturnValueOnce(runBPromise);                       // run 20, first fetch — held

    render(<ShellPage {...defaultProps()} />);

    // Navigate to run 10.
    act(() => setHash("/projects/1/runs/10/dashboard"));

    // Let run 10's summary resolve.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Summary A should be visible (DashboardTab renders the target URL).
    await waitFor(() =>
      expect(screen.getByTestId("dashboard-tab")).toHaveTextContent("http://run10.test"),
    );

    // Switch to run 20. Run B's fetch is still pending.
    act(() => setHash("/projects/2/runs/20/dashboard"));

    // At this point, BEFORE run B resolves, the tab content should NOT show
    // run A's summary. It should show the loading placeholder.
    await waitFor(() =>
      expect(screen.getByTestId("empty-tab")).toHaveTextContent("Loading run..."),
    );
    expect(screen.queryByTestId("dashboard-tab")).not.toBeInTheDocument();

    // Now resolve run B's summary.
    act(() => resolveRunB(mkSummary("http://run20.test")));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Run B's data should now be displayed.
    await waitFor(() =>
      expect(screen.getByTestId("dashboard-tab")).toHaveTextContent("http://run20.test"),
    );
  });

  it("refreshes projects after a stop request so the run state can transition promptly", async () => {
    const onRefreshProjects = vi.fn().mockResolvedValue(undefined);
    mockGetRunSummary.mockResolvedValue(mkSummary("http://run10.test"));
    mockStopRun.mockResolvedValue(undefined);

    render(<ShellPage {...defaultProps({ onRefreshProjects })} />);
    act(() => setHash("/projects/1/runs/10/dashboard"));

    await waitFor(() =>
      expect(screen.getByTestId("dashboard-tab")).toHaveTextContent("http://run10.test"),
    );

    await act(async () => {
      screen.getByText("STOP").click();
      await Promise.resolve();
    });

    expect(mockStopRun).toHaveBeenCalledWith("tok", 1, 10);
    expect(onRefreshProjects).toHaveBeenCalledTimes(1);
  });
});
