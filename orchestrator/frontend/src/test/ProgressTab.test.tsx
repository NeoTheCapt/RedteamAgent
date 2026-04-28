import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ProgressTab } from "../components/progress/ProgressTab";
import type { RunSummary } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    listDispatches: vi.fn(),
    listCases: vi.fn(),
  };
});

import { listDispatches, listCases } from "../lib/api";

const mockDispatches = listDispatches as unknown as ReturnType<typeof vi.fn>;
const mockCases = listCases as unknown as ReturnType<typeof vi.fn>;

function mkSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    target: {
      target: "http://x",
      hostname: "x",
      scheme: "http",
      path: "/",
      port: 80,
      scope_entries: [],
      engagement_dir: "/tmp/engagement",
      started_at: "2026-04-17T00:00:00Z",
      status: "running",
    },
    overview: {
      findings_count: 2,
      active_agents: 2,
      available_agents: 7,
      current_phase: "consume-test",
      updated_at: "2026-04-17T00:10:00Z",
    },
    runtime_model: {
      configured_provider: "",
      configured_model: "",
      configured_small_model: "",
      observed_provider: "",
      observed_model: "",
      status: "",
      summary: "",
    },
    coverage: {
      total_cases: 41,
      completed_cases: 3,
      pending_cases: 38,
      processing_cases: 0,
      error_cases: 0,
      case_types: [],
      total_surfaces: 15,
      remaining_surfaces: 4,
      high_risk_remaining: 2,
      surface_statuses: {},
      surface_types: [],
    },
    current: { phase: "consume-test", task_name: "", agent_name: "", summary: "" },
    phases: [
      { phase: "recon", label: "Recon", state: "completed", task_events: 1, active_agents: 0, latest_summary: "Recon target surface completed" },
      { phase: "collect", label: "Collect", state: "completed", task_events: 1, active_agents: 0, latest_summary: "Queued endpoints from recon and source analysis" },
      { phase: "consume-test", label: "Consume", state: "active", task_events: 1, active_agents: 2, latest_summary: "Analysis start" },
      { phase: "exploit", label: "Exploit", state: "pending", task_events: 0, active_agents: 0, latest_summary: "Exploit summary" },
      { phase: "report", label: "Report", state: "pending", task_events: 0, active_agents: 0, latest_summary: "" },
    ],
    agents: [
      { agent_name: "vulnerability-analyst", phase: "consume-test", status: "active", task_name: "triage", summary: "", updated_at: "2026-04-17 00:10:00" },
      { agent_name: "source-analyzer", phase: "recon", status: "active", task_name: "scan", summary: "", updated_at: "2026-04-17 00:09:00" },
    ],
    dispatches: { total: 2, active: 2, done: 0, failed: 0 },
    cases: { total: 41, done: 3, running: 0, queued: 38, error: 0, findings: 2 },
    ...overrides,
  };
}

describe("ProgressTab", () => {
  beforeEach(() => {
    mockDispatches.mockReset();
    mockCases.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders 5 phase columns", async () => {
    mockDispatches.mockResolvedValue([]);
    mockCases.mockResolvedValue([]);
    const { container } = render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    const board = container.querySelector(".progress");
    expect(board).not.toBeNull();
    await waitFor(() => {
      expect(board?.querySelector('[data-phase="recon"] .kanban-col__name')).toHaveTextContent("Recon");
      expect(board?.querySelector('[data-phase="collect"] .kanban-col__name')).toHaveTextContent("Collect");
      expect(board?.querySelector('[data-phase="consume"] .kanban-col__name')).toHaveTextContent("Consume-Test");
      expect(board?.querySelector('[data-phase="exploit"] .kanban-col__name')).toHaveTextContent("Exploit");
      expect(board?.querySelector('[data-phase="report"] .kanban-col__name')).toHaveTextContent("Report");
    });
  });

  it("exports a 5-column layout hint so all progress phases can fit in one board view", async () => {
    mockDispatches.mockResolvedValue([]);
    mockCases.mockResolvedValue([]);
    const { container } = render(
      <ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />,
    );

    await waitFor(() => {
      expect(container.querySelector(".progress")).toHaveAttribute("data-phase-count", "5");
    });
  });

  it("renders a compact overview card for each of the 5 phases", async () => {
    mockDispatches.mockResolvedValue([]);
    mockCases.mockResolvedValue([]);
    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);

    await waitFor(() => {
      expect(screen.getAllByTestId("progress-overview-card")).toHaveLength(5);
    });
  });

  it("groups dispatches into their phase columns", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "recon", round: 0, agent: "recon-specialist", slot: "s0", task: "nmap", state: "done", started_at: 1000, finished_at: 1100, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vuln-analyst", slot: "s0", task: "SQLi probes", state: "running", started_at: 2000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      // Each agent appears at least twice now: once in the per-phase
      // overview activity line (kept across phase transitions so the
      // record persists after the phase completes), and once in the
      // kanban DispatchCard for the active column.
      expect(screen.getAllByText("recon-specialist").length).toBeGreaterThan(0);
      expect(screen.getAllByText("vuln-analyst").length).toBeGreaterThan(0);
    });
  });

  it("retains a per-phase agent activity line for completed phases", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "recon", round: 0, agent: "recon-specialist", slot: "s0", task: "nmap", state: "done", started_at: 1000, finished_at: 1180, error: null },
      { id: "d2", phase: "recon", round: 0, agent: "source-analyzer", slot: "s0", task: "JS bundle scan", state: "done", started_at: 1100, finished_at: 1300, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 1, method: "GET", path: "/main.js", category: null, dispatch_id: "d2", state: "done", result: null, finding_id: null, started_at: null, finished_at: null, duration_ms: null },
      { case_id: 2, method: "GET", path: "/admin", category: null, dispatch_id: "d2", state: "finding", result: null, finding_id: "F-1", started_at: null, finished_at: null, duration_ms: null },
    ]);

    // currentPhase="consume" means recon is in the past — its activity
    // record must still appear in the recon overview card.
    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      const lines = screen.getAllByTestId("progress-overview-agent");
      const reconAgents = lines.filter((el) => el.textContent?.includes("recon-specialist"));
      const sourceAgents = lines.filter((el) => el.textContent?.includes("source-analyzer"));
      expect(reconAgents.length).toBeGreaterThan(0);
      expect(sourceAgents.length).toBeGreaterThan(0);
      // source-analyzer touched 2 cases including 1 finding
      expect(sourceAgents.some((el) => el.textContent?.includes("2 cases"))).toBe(true);
      expect(sourceAgents.some((el) => el.textContent?.includes("1 finding"))).toBe(true);
    });
  });

  it("shows case chips inside their dispatch card", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "vuln-analyst", slot: "s0", task: null, state: "running", started_at: 1000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 1, method: "GET", path: "/api/products", category: "injection", dispatch_id: "d1", state: "done", result: "no injection", finding_id: null, started_at: null, finished_at: null, duration_ms: null },
      { case_id: 2, method: "GET", path: "/api/search", category: "injection", dispatch_id: "d1", state: "finding", result: "SQLi", finding_id: "F-3", started_at: null, finished_at: null, duration_ms: 12000 },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      expect(screen.getByText("/api/products")).toBeInTheDocument();
      expect(screen.getByText("/api/search")).toBeInTheDocument();
    });
  });

  it("expands a case chip on click", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "v", slot: "s0", task: null, state: "running", started_at: 1, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 42, method: "POST", path: "/api/x", category: null, dispatch_id: "d1", state: "finding", result: "bug", finding_id: "F-42", started_at: null, finished_at: null, duration_ms: null },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => screen.getByText("/api/x"));

    expect(screen.queryByText("F-42")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("/api/x"));
    expect(await screen.findByText("F-42")).toBeInTheDocument();
  });

  it("surfaces an error banner when the fetch fails", async () => {
    mockDispatches.mockRejectedValue(new Error("backend down"));
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("backend down");
    });
  });

  it("renders orphaned (dispatch_id=null) cases as unassigned in the active phase", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "v", slot: "s0", task: null, state: "running", started_at: 1, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 99, method: "GET", path: "/api/orphan", category: null, dispatch_id: null, state: "queued", result: null, finding_id: null, started_at: null, finished_at: null, duration_ms: null },
      { case_id: 1, method: "GET", path: "/api/normal", category: null, dispatch_id: "d1", state: "done", result: null, finding_id: null, started_at: null, finished_at: null, duration_ms: null },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => screen.getByText("/api/orphan"));
    expect(screen.getByText("unassigned")).toBeInTheDocument();
    expect(screen.getByText("/api/normal")).toBeInTheDocument();
  });

  it("renders slot label as :s0 not :ss0 when parallel_dispatch emits s-prefixed slot ids", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "vuln-analyst", slot: "s0", task: null, state: "running", started_at: 1000, finished_at: null, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vuln-analyst", slot: "s1", task: null, state: "running", started_at: 1000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      expect(screen.getByText(":s0")).toBeInTheDocument();
      expect(screen.getByText(":s1")).toBeInTheDocument();
      expect(screen.queryByText(":ss0")).not.toBeInTheDocument();
      expect(screen.queryByText(":ss1")).not.toBeInTheDocument();
    });
  });

  it("renders phase-specific summaries and an agent breakdown", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "vulnerability-analyst", slot: "s0", task: null, state: "running", started_at: 1, finished_at: null, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vulnerability-analyst", slot: "s1", task: null, state: "running", started_at: 2, finished_at: null, error: null },
      { id: "d3", phase: "recon", round: 0, agent: "source-analyzer", slot: "s0", task: null, state: "done", started_at: 0, finished_at: 1, error: null },
    ]);
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);

    await waitFor(() => {
      expect(screen.getByText("2 agents active")).toBeInTheDocument();
      expect(screen.getAllByText(/2× vulnerability-analyst/).length).toBeGreaterThan(0);
      expect(screen.getAllByText("Recon target surface completed").length).toBeGreaterThan(0);
      expect(screen.getAllByText(/15 surface candidates recorded/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Report path \/tmp\/engagement\/report.md/).length).toBeGreaterThan(0);
    });
  });

  it("uses backend parallel_count when live dispatch rows undercount progress participation", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "exploit", round: 3, agent: "exploit-developer", slot: "s0", task: null, state: "running", started_at: 1, finished_at: null, error: null },
      { id: "d2", phase: "consume", round: 2, agent: "vulnerability-analyst", slot: "s0", task: null, state: "running", started_at: 2, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([]);
    const base = mkSummary();

    render(
      <ProgressTab
        token="t"
        projectId={1}
        runId={2}
        currentPhase="exploit"
        summary={mkSummary({
          overview: {
            ...base.overview,
            active_agents: 1,
            current_phase: "exploit",
          },
          agents: [
            {
              agent_name: "exploit-developer",
              phase: "exploit",
              status: "active",
              task_name: "exploit",
              summary: "Exploit start",
              updated_at: "2026-04-17 00:12:00",
              parallel_count: 12,
            },
            {
              agent_name: "vulnerability-analyst",
              phase: "consume-test",
              status: "completed",
              task_name: "triage",
              summary: "API batch completed",
              updated_at: "2026-04-17 00:11:00",
              parallel_count: 10,
            },
          ],
        })}
      />,
    );

    await waitFor(() => {
      const meta = screen.getByLabelText("Agent participation summary");
      expect(meta).toHaveTextContent("12× exploit-developer");
      expect(meta).toHaveTextContent("10× vulnerability-analyst");
      expect(meta).not.toHaveTextContent("1× exploit-developer, 1× vulnerability-analyst");
    });
  });

  it("keeps the progress-tab participation breakdown visible even after active agents drop to zero", async () => {
    mockDispatches.mockResolvedValue([]);
    mockCases.mockResolvedValue([]);
    const base = mkSummary();

    render(
      <ProgressTab
        token="t"
        projectId={1}
        runId={2}
        currentPhase="consume"
        summary={mkSummary({
          overview: {
            ...base.overview,
            active_agents: 0,
          },
          agents: [
            {
              agent_name: "vulnerability-analyst",
              phase: "consume-test",
              status: "idle",
              task_name: "triage",
              summary: "Test authenticated API batch",
              updated_at: "2026-04-17 00:10:00",
              parallel_count: 3,
            },
          ],
        })}
      />,
    );

    await waitFor(() => {
      const meta = screen.getByLabelText("Agent participation summary");
      expect(meta).toHaveTextContent("0 agents active");
      expect(meta).toHaveTextContent("1 agent type tracked");
      expect(meta).toHaveTextContent("3× vulnerability-analyst");
      expect(meta).not.toHaveTextContent(/full breakdown on the Dashboard tab/i);
    });
  });

  it("keeps completed agents in the progress breakdown after a run fails", async () => {
    mockDispatches.mockResolvedValue([]);
    mockCases.mockResolvedValue([]);
    const base = mkSummary();

    render(
      <ProgressTab
        token="t"
        projectId={1}
        runId={2}
        currentPhase="recon"
        summary={mkSummary({
          target: {
            ...base.target,
            status: "failed",
          },
          overview: {
            ...base.overview,
            active_agents: 0,
            current_phase: "recon",
          },
          agents: [
            {
              agent_name: "operator",
              phase: "recon",
              status: "completed",
              task_name: "bash",
              summary: "Shows dispatcher queue statistics completed",
              updated_at: "2026-04-17 00:11:48",
            },
            {
              agent_name: "recon-specialist",
              phase: "recon",
              status: "completed",
              task_name: "recon-specialist",
              summary: "Recon target completed",
              updated_at: "2026-04-17 00:09:59",
            },
            {
              agent_name: "source-analyzer",
              phase: "recon",
              status: "completed",
              task_name: "source-analyzer",
              summary: "Analyze source completed",
              updated_at: "2026-04-17 00:11:02",
            },
          ],
        })}
      />,
    );

    await waitFor(() => {
      const meta = screen.getByLabelText("Agent participation summary");
      expect(meta).toHaveTextContent("0 agents active");
      expect(meta).toHaveTextContent("3 agent types tracked");
      expect(meta).toHaveTextContent("1× operator, 1× recon-specialist, 1× source-analyzer");
    });
  });
});
