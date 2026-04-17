import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { NewRunForm } from "../components/home/NewRunForm";
import type { Project } from "../lib/api";

function mkProject(o: Partial<Project> = {}): Project {
  return {
    id: 1, name: "P1", slug: "p1", root_path: "/x",
    provider_id: "", model_id: "", small_model_id: "", base_url: "",
    api_key_configured: false, auth_configured: false, env_configured: false,
    ...o,
  } as Project;
}

describe("NewRunForm", () => {
  it("renders title and project dropdown", () => {
    render(
      <NewRunForm
        projects={[mkProject({ id: 1, name: "Alpha" })]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );
    expect(screen.getByText("New Engagement")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("disables submit when no target is entered", () => {
    render(
      <NewRunForm
        projects={[mkProject()]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /LAUNCH/i })).toBeDisabled();
  });

  it("calls onCreateRun with projectId + trimmed target on submit", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <NewRunForm
        projects={[mkProject({ id: 7, name: "Beta" })]}
        onCreateRun={onCreate}
        onCreateProject={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByRole("textbox"), "  http://ex.test  ");
    await userEvent.click(screen.getByRole("button", { name: /LAUNCH/i }));
    expect(onCreate).toHaveBeenCalledWith(7, "http://ex.test");
  });

  it("shows an error banner when onCreateRun rejects", async () => {
    const onCreate = vi.fn().mockRejectedValue(new Error("nope"));
    render(
      <NewRunForm
        projects={[mkProject()]}
        onCreateRun={onCreate}
        onCreateProject={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByRole("textbox"), "http://x");
    await userEvent.click(screen.getByRole("button", { name: /LAUNCH/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("handles empty projects list gracefully", () => {
    render(
      <NewRunForm
        projects={[]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );
    expect(screen.getByText(/No projects/)).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("creates project via create-project sub-form when no projects exist", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(undefined);
    render(
      <NewRunForm
        projects={[]}
        onCreateRun={vi.fn()}
        onCreateProject={onCreateProject}
      />,
    );
    // Create-project block is auto-expanded when projects=[]
    const input = screen.getByPlaceholderText(/e.g. juice-shop-lab/i);
    await userEvent.type(input, "new-proj");
    await userEvent.click(screen.getByRole("button", { name: /Create project/i }));
    expect(onCreateProject).toHaveBeenCalledWith("new-proj");
  });

  it("toggles create-project block visibility with the link", async () => {
    render(
      <NewRunForm
        projects={[mkProject({ id: 1, name: "existing" })]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
      />,
    );
    // With existing projects, create block is collapsed by default.
    expect(screen.queryByPlaceholderText(/e.g. juice-shop-lab/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /\+ Create project/i }));
    expect(screen.getByPlaceholderText(/e.g. juice-shop-lab/i)).toBeInTheDocument();
  });
});
