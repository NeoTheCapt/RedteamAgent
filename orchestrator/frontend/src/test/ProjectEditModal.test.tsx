import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FormEvent } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ProjectEditModal } from "../components/projects/ProjectEditModal";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, updateProject: vi.fn() };
});
import { updateProject } from "../lib/api";
const mockUpdate = updateProject as unknown as ReturnType<typeof vi.fn>;

function mkProject(overrides: Partial<import("../lib/api").Project> = {}): import("../lib/api").Project {
  return {
    id: 1, name: "demo", slug: "demo",
    provider_id: "", model_id: "", small_model_id: "",
    api_key: "", base_url: "",
    auth_json: "", env_json: "",
    crawler_json: "{}", parallel_json: "{}", agents_json: "{}",
    created_at: "",
    ...overrides,
  };
}

beforeEach(() => mockUpdate.mockReset());

describe("ProjectEditModal", () => {
  it("returns null when open=false", () => {
    const { container } = render(
      <ProjectEditModal open={false} token="t" project={mkProject()}
        onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("patches the project with drafted Model fields on save", async () => {
    const project = mkProject({ model_id: "old" });
    const onSaved = vi.fn();
    mockUpdate.mockResolvedValue({ ...project, model_id: "gpt-4o" });
    render(<ProjectEditModal open={true} token="t" project={project}
      onClose={vi.fn()} onSaved={onSaved} />);
    await userEvent.clear(screen.getByLabelText(/model id/i));
    await userEvent.type(screen.getByLabelText(/model id/i), "gpt-4o");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith("t", 1, expect.objectContaining({ model_id: "gpt-4o" }));
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("toggles an agent from enabled to disabled and persists as JSON", async () => {
    const project = mkProject({ agents_json: "{}" });
    const onSaved = vi.fn();
    mockUpdate.mockResolvedValue({ ...project, agents_json: '{"fuzzer":false}' });
    render(<ProjectEditModal open={true} token="t" project={project}
      onClose={vi.fn()} onSaved={onSaved} />);
    await userEvent.click(screen.getByRole("tab", { name: "Agents" }));
    await userEvent.click(screen.getByLabelText("fuzzer"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const call = mockUpdate.mock.calls[0][2];
      expect(JSON.parse((call as { agents_json: string }).agents_json)).toEqual({ fuzzer: false });
    });
  });

  it("surfaces save error to user", async () => {
    // Use mockRejectedValueOnce to avoid Vitest 4's unhandled-rejection tracking
    // of permanent mockRejectedValue implementations.
    mockUpdate.mockRejectedValueOnce(new Error("forbidden"));
    const project = mkProject();
    render(<ProjectEditModal open={true} token="t" project={project}
      onClose={vi.fn()} onSaved={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("forbidden"));
  });

  it("switches tabs without losing drafted changes", async () => {
    const project = mkProject({ model_id: "old" });
    render(<ProjectEditModal open={true} token="t" project={project}
      onClose={vi.fn()} onSaved={vi.fn()} />);
    await userEvent.clear(screen.getByLabelText(/model id/i));
    await userEvent.type(screen.getByLabelText(/model id/i), "gpt-4o");
    await userEvent.click(screen.getByRole("tab", { name: "Crawler" }));
    await userEvent.click(screen.getByRole("tab", { name: "Model" }));
    expect(screen.getByLabelText(/model id/i)).toHaveValue("gpt-4o");
  });

  it("keeps tab buttons from submitting an enclosing form and persists crawler depth", async () => {
    const onSubmit = vi.fn((event: FormEvent<HTMLFormElement>) => event.preventDefault());
    const project = mkProject({ crawler_json: "{}" });
    mockUpdate.mockResolvedValue({ ...project, crawler_json: '{"KATANA_CRAWL_DEPTH":16}' });

    render(
      <form onSubmit={onSubmit}>
        <ProjectEditModal open={true} token="t" project={project}
          onClose={vi.fn()} onSaved={vi.fn()} />
      </form>,
    );

    await userEvent.click(screen.getByRole("tab", { name: "Crawler" }));
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText(/crawl depth/i));
    await userEvent.type(screen.getByLabelText(/crawl depth/i), "16");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = mockUpdate.mock.calls[0][2];
      expect(JSON.parse((call as { crawler_json: string }).crawler_json)).toEqual({ KATANA_CRAWL_DEPTH: 16 });
    });
  });
});
