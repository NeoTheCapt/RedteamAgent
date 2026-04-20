import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DashboardTab } from "../components/dashboard/DashboardTab";
import type { RunSummary } from "../lib/api";

function mkSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    target: {
      target: "http://x", hostname: "x", scheme: "http", path: "/",
      port: 80, scope_entries: [], engagement_dir: "/x",
      started_at: "2026-04-17T00:00:00Z", status: "running",
    },
    overview: {
      findings_count: 3,
      active_agents: 2,
      available_agents: 5,
      current_phase: "consume-test",
      updated_at: "2026-04-17T00:10:00Z",
    },
    runtime_model: {
      configured_provider: "", configured_model: "", configured_small_model: "",
      observed_provider: "", observed_model: "", status: "", summary: "",
    },
    coverage: {
      total_cases: 10, completed_cases: 7, pending_cases: 2,
      processing_cases: 1, error_cases: 0,
      case_types: [
        { type: "api", total: 5, done: 4 },
        { type: "javascript", total: 3, done: 2 },
      ],
      total_surfaces: 0, remaining_surfaces: 0, high_risk_remaining: 0,
      surface_statuses: {}, surface_types: [],
    },
    current: { phase: "consume-test", task_name: "", agent_name: "", summary: "" },
    phases: [
      { phase: "recon", label: "Recon", state: "completed", task_events: 0, active_agents: 0, latest_summary: "" },
      { phase: "collect", label: "Collect", state: "completed", task_events: 0, active_agents: 0, latest_summary: "" },
      { phase: "consume-test", label: "Consume", state: "active", task_events: 0, active_agents: 0, latest_summary: "" },
    ],
    agents: [],
    dispatches: { total: 3, active: 1, done: 2, failed: 0 },
    cases: { total: 10, done: 6, running: 1, queued: 2, error: 0, findings: 1 },
    ...overrides,
  };
}

describe("DashboardTab", () => {
  it("renders all five KPI labels", () => {
    render(<DashboardTab summary={mkSummary()} />);
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect(screen.getByText("Cases Tested")).toBeInTheDocument();
    expect(screen.getByText("Dispatched")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
    expect(screen.getByText("Active Agents")).toBeInTheDocument();
  });

  it("shows findings count from summary.overview.findings_count", () => {
    render(<DashboardTab summary={mkSummary({
      overview: { ...mkSummary().overview, findings_count: 18 },
    })} />);
    // The KPI value appears multiple times if other cards mention it; just
    // confirm the value "18" is present somewhere in the rendered output.
    expect(screen.getAllByText("18").length).toBeGreaterThan(0);
  });

  it("renders all 5 phase strip steps", () => {
    render(<DashboardTab summary={mkSummary()} />);
    for (const p of ["RECON", "COLLECT", "CONSUME", "EXPLOIT", "REPORT"]) {
      expect(screen.getByText(p)).toBeInTheDocument();
    }
  });

  it("marks completed phases as done and current as active", () => {
    const { container } = render(<DashboardTab summary={mkSummary()} />);
    const doneSteps = container.querySelectorAll(".phase-strip__step--done");
    expect(doneSteps.length).toBe(2); // recon + collect
    const activeSteps = container.querySelectorAll(".phase-strip__step--active");
    expect(activeSteps.length).toBe(1); // consume
  });

  it("renders CategoryBars with at least one visible type", () => {
    render(<DashboardTab summary={mkSummary()} />);
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByText("javascript")).toBeInTheDocument();
  });

  it("shows empty state for CategoryBars when no case types", () => {
    render(<DashboardTab summary={mkSummary({
      coverage: { ...mkSummary().coverage, case_types: [] },
    })} />);
    expect(screen.getByText("No cases processed yet.")).toBeInTheDocument();
  });

  it("renders SeverityDonut", () => {
    render(<DashboardTab summary={mkSummary()} />);
    expect(screen.getByText(/Per-severity breakdown/)).toBeInTheDocument();
  });
});
