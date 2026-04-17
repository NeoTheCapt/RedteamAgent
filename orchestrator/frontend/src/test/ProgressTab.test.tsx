import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ProgressTab } from "../components/progress/ProgressTab";

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
    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
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
      { id: "d1", phase: "recon", round: 0, agent: "recon-specialist",
        slot: "0", task: "nmap", state: "done",
        started_at: 1000, finished_at: 1100, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vuln-analyst",
        slot: "0", task: "SQLi probes", state: "running",
        started_at: 2000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => {
      expect(screen.getByText("recon-specialist")).toBeInTheDocument();
      expect(screen.getByText("vuln-analyst")).toBeInTheDocument();
    });
  });

  it("shows case chips inside their dispatch card", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "vuln-analyst",
        slot: "0", task: null, state: "running",
        started_at: 1000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 1, method: "GET", path: "/api/products",
        category: "injection", dispatch_id: "d1",
        state: "done", result: "no injection", finding_id: null,
        started_at: null, finished_at: null, duration_ms: null },
      { case_id: 2, method: "GET", path: "/api/search",
        category: "injection", dispatch_id: "d1",
        state: "finding", result: "SQLi", finding_id: "F-3",
        started_at: null, finished_at: null, duration_ms: 12000 },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => {
      expect(screen.getByText("/api/products")).toBeInTheDocument();
      expect(screen.getByText("/api/search")).toBeInTheDocument();
    });
  });

  it("expands a case chip on click", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "v", slot: "0",
        task: null, state: "running", started_at: 1, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      { case_id: 42, method: "POST", path: "/api/x",
        category: null, dispatch_id: "d1",
        state: "finding", result: "bug", finding_id: "F-42",
        started_at: null, finished_at: null, duration_ms: null },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => screen.getByText("/api/x"));

    // Detail block hidden initially
    expect(screen.queryByText("F-42")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("/api/x"));

    // After click, detail block reveals finding_id
    expect(await screen.findByText("F-42")).toBeInTheDocument();
  });

  it("surfaces an error banner when the fetch fails", async () => {
    mockDispatches.mockRejectedValue(new Error("backend down"));
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("backend down");
    });
  });
});
