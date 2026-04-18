import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { CaseSidePanel } from "../components/cases/CaseSidePanel";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, getCase: vi.fn() };
});
import { getCase } from "../lib/api";
const mockGet = getCase as unknown as ReturnType<typeof vi.fn>;

describe("CaseSidePanel", () => {
  it("fetches + renders case detail", async () => {
    mockGet.mockResolvedValue({
      case_id: 32, method: "GET", path: "/api/search",
      category: "injection", dispatch_id: "B-17",
      state: "finding", result: "SQLi", finding_id: "F-3",
      started_at: 1700000000, finished_at: 1700000012, duration_ms: 12000,
    });
    render(
      <CaseSidePanel token="t" projectId={1} runId={2} caseId={32} onClose={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText("/api/search")).toBeInTheDocument());
    expect(screen.getByText("F-3")).toBeInTheDocument();
    expect(screen.getByText("GET")).toBeInTheDocument();
    expect(screen.getByText("12.0s")).toBeInTheDocument();
  });

  it("shows an error message if fetch fails", async () => {
    mockGet.mockRejectedValue(new Error("404"));
    render(
      <CaseSidePanel token="t" projectId={1} runId={2} caseId={999} onClose={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("404");
    });
  });

  it("calls onClose when the close button is clicked", async () => {
    mockGet.mockResolvedValue({
      case_id: 1, method: "GET", path: "/", category: null,
      dispatch_id: null, state: "queued", result: null, finding_id: null,
      started_at: null, finished_at: null, duration_ms: null,
    });
    const onClose = vi.fn();
    render(
      <CaseSidePanel token="t" projectId={1} runId={2} caseId={1} onClose={onClose} />,
    );
    await waitFor(() => screen.getByText("queued"));
    await userEvent.click(screen.getByLabelText("Close detail"));
    expect(onClose).toHaveBeenCalled();
  });
});
