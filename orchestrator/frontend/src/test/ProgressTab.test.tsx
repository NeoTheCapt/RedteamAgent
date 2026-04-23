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
    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" summary={mkSummary()} />);
    await waitFor(() => {
      expect(screen.getByText("Recon")).toBeInTheDocument();
      expect(screen.getByText("Collect")).toBeInTheDocument();
      expect(screen.getByText("Consume-Test")).toBeInTheDocument();
      expect(screen.getByText("Exploit")).toBeInTheDocument();
      expect(screen.getByText("Report")).toBeInTheDocument();
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
      expect(screen.getByText("recon-specialist")).toBeInTheDocument();
      expect(screen.getByText("vuln-analyst")).toBeInTheDocument();
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
      expect(screen.getByText(/2× vulnerability-analyst/)).toBeInTheDocument();
      expect(screen.getByText("Recon target surface completed")).toBeInTheDocument();
      expect(screen.getByText(/15 surface candidates recorded/)).toBeInTheDocument();
      expect(screen.getByText(/Report path \/tmp\/engagement\/report.md/)).toBeInTheDocument();
    });
  });
});
