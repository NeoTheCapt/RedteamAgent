import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CasesTab } from "../components/cases/CasesTab";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    listCases: vi.fn(),
    getCase: vi.fn(),
  };
});
import { listCases, getCase } from "../lib/api";
const mockList = listCases as unknown as ReturnType<typeof vi.fn>;
const mockGet = getCase as unknown as ReturnType<typeof vi.fn>;

const mkCase = (o: Record<string, unknown> = {}) => ({
  case_id: 1, method: "GET", path: "/x", category: null,
  dispatch_id: null, state: "done", result: null, finding_id: null,
  started_at: null, finished_at: null, duration_ms: null, ...o,
});

beforeEach(() => {
  mockList.mockReset();
  mockGet.mockReset();
  window.location.hash = "";
});

describe("CasesTab", () => {
  it("renders cases returned by the backend", async () => {
    mockList.mockResolvedValue([
      mkCase({ case_id: 1, path: "/api/a", state: "done" }),
      mkCase({ case_id: 2, path: "/api/b", state: "finding", finding_id: "F-2" }),
    ]);
    render(<CasesTab token="t" projectId={1} runId={2} />);
    await waitFor(() => expect(screen.getByText("/api/a")).toBeInTheDocument());
    expect(screen.getByText("/api/b")).toBeInTheDocument();
    expect(screen.getByText("F-2")).toBeInTheDocument();
  });

  it("passes state/method/category to the backend when filters change", async () => {
    mockList.mockResolvedValue([]);
    render(<CasesTab token="t" projectId={1} runId={2} />);
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    expect(mockList).toHaveBeenLastCalledWith("t", 1, 2, {
      state: undefined, method: undefined, category: undefined,
    });

    const stateSelect = screen.getByLabelText("State");
    await userEvent.selectOptions(stateSelect, "finding");
    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith("t", 1, 2, {
        state: "finding", method: undefined, category: undefined,
      });
    });
  });

  it("filters by search query client-side", async () => {
    mockList.mockResolvedValue([
      mkCase({ case_id: 1, path: "/api/products" }),
      mkCase({ case_id: 2, path: "/api/search", finding_id: "F-2" }),
    ]);
    render(<CasesTab token="t" projectId={1} runId={2} />);
    await waitFor(() => screen.getByText("/api/products"));

    const searchInput = screen.getByLabelText("Search");
    await userEvent.type(searchInput, "search");
    await waitFor(() => {
      expect(screen.queryByText("/api/products")).not.toBeInTheDocument();
    });
    expect(screen.getByText("/api/search")).toBeInTheDocument();
  });

  it("opens side panel on row click and closes on second click", async () => {
    mockList.mockResolvedValue([mkCase({ case_id: 7, path: "/api/x" })]);
    mockGet.mockResolvedValue(mkCase({ case_id: 7, path: "/api/x" }));

    render(<CasesTab token="t" projectId={1} runId={2} />);
    await waitFor(() => screen.getByText("/api/x"));

    // Data row is the 2nd row (after the header row).
    const dataRow = () => screen.getAllByRole("row")[1];

    await userEvent.click(dataRow());
    await waitFor(() => expect(screen.getByLabelText(/^Case 7$/)).toBeInTheDocument());

    // Second click toggles selection off
    await userEvent.click(dataRow());
    await waitFor(() => {
      expect(screen.queryByLabelText(/^Case 7$/)).not.toBeInTheDocument();
    });
  });

  it("syncs filters to the URL hash", async () => {
    mockList.mockResolvedValue([]);
    render(<CasesTab token="t" projectId={1} runId={2} />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());

    await userEvent.selectOptions(screen.getByLabelText("State"), "finding");
    await waitFor(() => {
      expect(window.location.hash).toContain("state=finding");
    });
  });
});
