import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DocumentsTab } from "../components/documents/DocumentsTab";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, listDocuments: vi.fn(), getDocument: vi.fn() };
});
import { listDocuments, getDocument } from "../lib/api";
const mockList = listDocuments as unknown as ReturnType<typeof vi.fn>;
const mockGet = getDocument as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockList.mockReset();
  mockGet.mockReset();
});

describe("DocumentsTab", () => {
  it("renders the 5-bucket tree", async () => {
    mockList.mockResolvedValue({
      findings: [{ name: "f1.md", path: "findings/f1.md", size: 1024, mtime: 0 }],
      reports: [],
      intel: [{ name: "recon.md", path: "intel/recon.md", size: 512, mtime: 0 }],
      surface: [],
      other: [],
    });
    render(<DocumentsTab token="t" projectId={1} runId={2} />);
    await waitFor(() => screen.getByText("f1.md"));
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect(screen.getByText("Intel")).toBeInTheDocument();
    expect(screen.getByText("recon.md")).toBeInTheDocument();
  });

  it("shows empty-state when the engagement has no documents yet", async () => {
    mockList.mockResolvedValue({
      findings: [], reports: [], intel: [], surface: [], other: [],
    });
    render(<DocumentsTab token="t" projectId={1} runId={2} />);
    await waitFor(() => screen.getByText(/No documents/));
  });

  it("loads content into the preview when a file is clicked", async () => {
    mockList.mockResolvedValue({
      findings: [{ name: "f1.md", path: "findings/f1.md", size: 100, mtime: 0 }],
      reports: [], intel: [], surface: [], other: [],
    });
    mockGet.mockResolvedValue({ path: "findings/f1.md", content: "# Hi" });
    render(<DocumentsTab token="t" projectId={1} runId={2} />);
    await waitFor(() => screen.getByText("f1.md"));
    await userEvent.click(screen.getByText("f1.md"));
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Hi"),
    );
  });

  it("displays an error banner when the list fetch fails", async () => {
    mockList.mockRejectedValue(new Error("denied"));
    render(<DocumentsTab token="t" projectId={1} runId={2} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("denied"),
    );
  });

  it("clears selectedPath when the file disappears from a subsequent poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const treeWith = {
      findings: [{ name: "a.md", path: "findings/a.md", size: 100, mtime: 0 }],
      reports: [], intel: [], surface: [], other: [],
    };
    const treeWithout = {
      findings: [],
      reports: [], intel: [], surface: [], other: [],
    };

    mockList.mockResolvedValueOnce(treeWith);
    mockGet.mockResolvedValue({ path: "findings/a.md", content: "# Hello" });

    render(<DocumentsTab token="t" projectId={1} runId={2} />);

    // Let the initial fetch resolve.
    await act(async () => { await Promise.resolve(); });
    await waitFor(() => screen.getByText("a.md"));

    // Click the file — preview loads.
    await act(async () => {
      await userEvent.click(screen.getByText("a.md"));
    });
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Hello"),
    );

    // Second poll returns tree without findings/a.md.
    mockList.mockResolvedValueOnce(treeWithout);
    await act(async () => {
      vi.advanceTimersByTime(10_000);
      // Drain microtasks so the resolved promise settles.
      await Promise.resolve();
      await Promise.resolve();
    });

    // selectedPath should be cleared → placeholder text appears.
    await waitFor(() =>
      expect(screen.getByText(/Select a document from the left/)).toBeInTheDocument(),
    );

    vi.useRealTimers();
  });
});
