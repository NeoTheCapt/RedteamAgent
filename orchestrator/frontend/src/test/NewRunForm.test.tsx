import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { NewRunForm } from "../components/home/NewRunForm";
import type { Project } from "../lib/api";

function mkProject(o: Partial<Project> = {}): Project {
  return {
    id: 1, name: "P1", slug: "p1", root_path: "/x",
    provider_id: "", model_id: "", small_model_id: "", base_url: "",
    api_key_configured: false, auth_configured: false, env_configured: false,
    crawler_json: "{}", parallel_json: "{}", agents_json: "{}",
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
        onEditProject={vi.fn()}
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
        onEditProject={vi.fn()}
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
        onEditProject={vi.fn()}
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
        onEditProject={vi.fn()}
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
        onEditProject={vi.fn()}
      />,
    );
    expect(screen.getByText(/No projects/)).toBeInTheDocument();
    // Use the label text to disambiguate from the Provider combobox in ModelFields.
    expect(screen.getByRole("combobox", { name: /use project/i })).toBeDisabled();
  });

  it("creates project via create-project sub-form when no projects exist", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(undefined);
    render(
      <NewRunForm
        projects={[]}
        onCreateRun={vi.fn()}
        onCreateProject={onCreateProject}
        onEditProject={vi.fn()}
      />,
    );
    // Create-project block is auto-expanded when projects=[]
    const input = screen.getByPlaceholderText(/e.g. juice-shop-lab/i);
    await userEvent.type(input, "new-proj");
    await userEvent.click(screen.getByRole("button", { name: /Create project/i }));
    expect(onCreateProject).toHaveBeenCalledWith(
      expect.objectContaining({ name: "new-proj" }),
    );
  });

  it("toggles create-project block visibility with the link", async () => {
    render(
      <NewRunForm
        projects={[mkProject({ id: 1, name: "existing" })]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
        onEditProject={vi.fn()}
      />,
    );
    // With existing projects, create block is collapsed by default.
    expect(screen.queryByPlaceholderText(/e.g. juice-shop-lab/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /\+ Create project/i }));
    expect(screen.getByPlaceholderText(/e.g. juice-shop-lab/i)).toBeInTheDocument();
  });

  it("Enter in project-name input triggers createProject, not onCreateRun (launch)", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(undefined);
    const onCreateRun = vi.fn().mockResolvedValue(undefined);
    render(
      <NewRunForm
        projects={[]}
        onCreateRun={onCreateRun}
        onCreateProject={onCreateProject}
        onEditProject={vi.fn()}
      />,
    );
    // Create-project block is auto-expanded when projects=[].
    const nameInput = screen.getByPlaceholderText(/e.g. juice-shop-lab/i);
    await userEvent.type(nameInput, "my-project");
    await userEvent.keyboard("{Enter}");
    expect(onCreateProject).toHaveBeenCalledWith(
      expect.objectContaining({ name: "my-project" }),
    );
    expect(onCreateRun).not.toHaveBeenCalled();
  });

  it("projectId syncs when projects arrive asynchronously after mount", async () => {
    const onCreateRun = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <NewRunForm
        projects={[]}
        onCreateRun={onCreateRun}
        onCreateProject={vi.fn()}
        onEditProject={vi.fn()}
      />,
    );
    // Initially no projects — dropdown disabled, launch button disabled.
    // Use the label name to disambiguate from the Provider combobox in ModelFields
    // (create block is auto-expanded when projects=[]).
    expect(screen.getByRole("combobox", { name: /use project/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /LAUNCH/i })).toBeDisabled();

    // Projects arrive (async load).
    rerender(
      <NewRunForm
        projects={[mkProject({ id: 42, name: "LateProject" })]}
        onCreateRun={onCreateRun}
        onCreateProject={vi.fn()}
        onEditProject={vi.fn()}
      />,
    );

    // Dropdown should now show the project and be enabled.
    expect(screen.getByText("LateProject")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /use project/i })).not.toBeDisabled();

    // Typing a target should enable Launch (use exact placeholder to avoid ambiguity
    // with the project-name input that is also visible when projects was initially empty).
    await userEvent.type(screen.getByPlaceholderText("http://juice-shop:8000"), "http://target");
    expect(screen.getByRole("button", { name: /LAUNCH/i })).not.toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /LAUNCH/i }));
    expect(onCreateRun).toHaveBeenCalledWith(42, "http://target");
  });

  it("includes Advanced Model fields in onCreateProject payload", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(undefined);
    render(
      <NewRunForm
        projects={[]}
        onCreateRun={vi.fn()}
        onCreateProject={onCreateProject}
        onEditProject={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText(/e.g. juice-shop-lab/i), "demo");
    // Open the Advanced <details> block.
    await userEvent.click(screen.getByText(/advanced/i));
    await userEvent.type(
      screen.getByPlaceholderText(/e\.g\. gpt-4o/i),
      "gpt-4o",
    );
    await userEvent.click(screen.getByRole("button", { name: /create project/i }));
    await waitFor(() =>
      expect(onCreateProject).toHaveBeenCalledWith(
        expect.objectContaining({ name: "demo", model_id: "gpt-4o" }),
      ),
    );
  });

  it("shows inherited config summary with Edit button when a project is selected", () => {
    const onEditProject = vi.fn();
    const project = mkProject({
      id: 42,
      name: "test-p",
      model_id: "gpt-4o",
      crawler_json: '{"KATANA_CRAWL_DEPTH": 4}',
    });
    render(
      <NewRunForm
        projects={[project]}
        onCreateRun={vi.fn()}
        onCreateProject={vi.fn()}
        onEditProject={onEditProject}
      />,
    );
    expect(screen.getByText(/Inherited from project/i)).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText(/1 override/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /edit project configuration/i }));
    expect(onEditProject).toHaveBeenCalledWith(project);
  });
});
