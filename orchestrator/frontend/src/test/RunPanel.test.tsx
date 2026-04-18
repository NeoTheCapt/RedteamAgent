import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RunPanel } from "../components/shell/RunPanel";
import type { Run } from "../lib/api";

function mkRun(s: Partial<Run> = {}): Run {
  return {
    id: 1, target: "t", status: "running", engagement_root: "/x",
    created_at: "", updated_at: "",
    ...s,
  } as Run;
}

describe("RunPanel", () => {
  it("shows target, id, phase badge, and STOP for active run", async () => {
    const onStop = vi.fn();
    render(
      <RunPanel run={mkRun({ target: "juice-shop", id: 42 })}
        currentPhase="consume-test"
        runtimeLabel="runtime 23m"
        onStop={onStop}
      >
        <div data-testid="children">x</div>
      </RunPanel>
    );
    expect(screen.getByText("juice-shop")).toBeInTheDocument();
    expect(screen.getByText("#r-42")).toBeInTheDocument();
    expect(screen.getByText("CONSUME-TEST")).toBeInTheDocument();
    expect(screen.getByText("runtime 23m")).toBeInTheDocument();
    await userEvent.click(screen.getByText("◼ STOP"));
    expect(onStop).toHaveBeenCalled();
    expect(screen.getByTestId("children")).toBeInTheDocument();
  });

  it("hides STOP and pulse dot when run is completed", () => {
    render(
      <RunPanel run={mkRun({ status: "completed" })} currentPhase="report" onStop={vi.fn()}>
        <div />
      </RunPanel>
    );
    expect(screen.queryByText("◼ STOP")).toBeNull();
    expect(screen.queryByLabelText("running")).toBeNull();
  });

  it("applies the done ribbon class on completed runs", () => {
    const { container } = render(
      <RunPanel run={mkRun({ status: "completed" })}><div /></RunPanel>
    );
    expect(container.querySelector(".run-panel--done")).toBeTruthy();
  });

  it("applies the stopped ribbon class (not failed) on stopped runs", () => {
    const { container } = render(
      <RunPanel run={mkRun({ status: "stopped" })}><div /></RunPanel>
    );
    expect(container.querySelector(".run-panel--stopped")).toBeTruthy();
    expect(container.querySelector(".run-panel--failed")).toBeNull();
  });

  it("hides STOP button for stopped runs", () => {
    render(
      <RunPanel run={mkRun({ status: "stopped" })} onStop={vi.fn()}>
        <div />
      </RunPanel>
    );
    expect(screen.queryByText("◼ STOP")).toBeNull();
  });
});
