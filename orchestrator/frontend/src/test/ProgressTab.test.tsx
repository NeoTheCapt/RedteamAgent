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
        slot: "s0", task: "nmap", state: "done",
        started_at: 1000, finished_at: 1100, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vuln-analyst",
        slot: "s0", task: "SQLi probes", state: "running",
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
        slot: "s0", task: null, state: "running",
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
      { id: "d1", phase: "consume", round: 1, agent: "v", slot: "s0",
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

  it("renders orphaned (dispatch_id=null) cases as unassigned in the active phase", async () => {
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "v", slot: "s0",
        task: null, state: "running", started_at: 1, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([
      // Case without a dispatch_id — was orphaned or delivered before dispatch_start
      { case_id: 99, method: "GET", path: "/api/orphan",
        category: null, dispatch_id: null,
        state: "queued", result: null, finding_id: null,
        started_at: null, finished_at: null, duration_ms: null },
      // Normal case under d1
      { case_id: 1, method: "GET", path: "/api/normal",
        category: null, dispatch_id: "d1",
        state: "done", result: null, finding_id: null,
        started_at: null, finished_at: null, duration_ms: null },
    ]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => screen.getByText("/api/orphan"));
    // Orphan is rendered in an "unassigned" slot (same column as active phase).
    expect(screen.getByText("unassigned")).toBeInTheDocument();
    // Normal case also rendered
    expect(screen.getByText("/api/normal")).toBeInTheDocument();
  });

  it("renders slot label as :s0 not :ss0 when parallel_dispatch emits s-prefixed slot ids", async () => {
    // parallel_dispatch.sh emits slot="s0", "s1", etc.  DispatchCard must render
    // ":s0" — not ":ss0" (the double-prefix bug fixed in this patch).
    mockDispatches.mockResolvedValue([
      { id: "d1", phase: "consume", round: 1, agent: "vuln-analyst",
        slot: "s0", task: null, state: "running",
        started_at: 1000, finished_at: null, error: null },
      { id: "d2", phase: "consume", round: 1, agent: "vuln-analyst",
        slot: "s1", task: null, state: "running",
        started_at: 1000, finished_at: null, error: null },
    ]);
    mockCases.mockResolvedValue([]);

    render(<ProgressTab token="t" projectId={1} runId={2} currentPhase="consume" />);
    await waitFor(() => {
      expect(screen.getByText(":s0")).toBeInTheDocument();
      expect(screen.getByText(":s1")).toBeInTheDocument();
      expect(screen.queryByText(":ss0")).not.toBeInTheDocument();
      expect(screen.queryByText(":ss1")).not.toBeInTheDocument();
    });
  });
});
