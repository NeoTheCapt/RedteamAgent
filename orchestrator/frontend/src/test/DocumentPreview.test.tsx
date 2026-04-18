import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DocumentPreview } from "../components/documents/DocumentPreview";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>(
    "../lib/api"
  );
  return { ...actual, getDocument: vi.fn() };
});
import { getDocument } from "../lib/api";
const mockGet = getDocument as unknown as ReturnType<typeof vi.fn>;

describe("DocumentPreview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows placeholder when path is null", () => {
    render(
      <DocumentPreview token="t" projectId={1} runId={2} path={null} />
    );
    expect(screen.getByText(/Select a document/)).toBeInTheDocument();
  });

  it("renders markdown for .md files", async () => {
    mockGet.mockResolvedValue({
      path: "findings/x.md",
      content: "# Title\n\nbody",
    });
    render(
      <DocumentPreview token="t" projectId={1} runId={2} path="findings/x.md" />
    );
    await waitFor(() => screen.getByText("Title"));
    // react-markdown produces an <h1>
    expect(
      screen.getByRole("heading", { level: 1 }).textContent
    ).toBe("Title");
  });

  it("renders raw text for .log files", async () => {
    mockGet.mockResolvedValue({
      path: "runtime/process.log",
      content: "line1\nline2",
    });
    render(
      <DocumentPreview
        token="t"
        projectId={1}
        runId={2}
        path="runtime/process.log"
      />
    );
    await waitFor(() => {
      expect(screen.getByText((_content, element) => {
        return element?.textContent === "line1\nline2";
      })).toBeInTheDocument();
    });
  });

  it("shows binary placeholder for non-text extensions", () => {
    render(
      <DocumentPreview
        token="t"
        projectId={1}
        runId={2}
        path="artifacts/x.png"
      />
    );
    expect(screen.getByText(/Binary file/)).toBeInTheDocument();
  });

  it("surfaces fetch errors", async () => {
    mockGet.mockRejectedValue(new Error("404"));
    render(
      <DocumentPreview
        token="t"
        projectId={1}
        runId={2}
        path="findings/missing.md"
      />
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("404");
    });
  });

  it("auto-refreshes content every 10 s without flashing the loading spinner", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // First fetch returns "A".
    mockGet.mockResolvedValueOnce({ path: "report.md", content: "A" });

    render(
      <DocumentPreview token="t" projectId={1} runId={2} path="report.md" />
    );

    // Initial load: wait for "A" to appear.
    await waitFor(() => expect(screen.queryByText("A")).toBeInTheDocument());

    // Loading spinner must not be visible after initial load.
    expect(screen.queryByText(/Loading/)).not.toBeInTheDocument();

    // Second fetch (auto-refresh tick after 10 s) returns "B".
    mockGet.mockResolvedValueOnce({ path: "report.md", content: "B" });

    await act(async () => {
      vi.advanceTimersByTime(10_000);
      // Flush the microtask queue so the async fetcher resolves.
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.queryByText("B")).toBeInTheDocument());

    // Loading spinner still must not be visible (no spinner during auto-refresh).
    expect(screen.queryByText(/Loading/)).not.toBeInTheDocument();
  });
});
