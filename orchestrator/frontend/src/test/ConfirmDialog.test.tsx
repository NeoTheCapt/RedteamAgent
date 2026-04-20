import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ConfirmDialog } from "../components/shell/ConfirmDialog";

// jsdom doesn't implement HTMLDialogElement.showModal; polyfill minimally.
beforeAll(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };
  }
});

describe("ConfirmDialog", () => {
  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open={true} title="Delete x" message="are you sure?"
        onConfirm={onConfirm} onCancel={onCancel} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("calls onCancel when the cancel button is clicked", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open={true} title="Delete x" message="are you sure?"
        onConfirm={onConfirm} onCancel={onCancel} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("renders destructive styling when flagged", () => {
    const { container } = render(
      <ConfirmDialog open={true} title="x" message="y" destructive
        onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(container.querySelector(".confirm-dialog__confirm--danger")).toBeInTheDocument();
  });

  it("custom confirmLabel overrides default", () => {
    render(
      <ConfirmDialog open={true} title="x" message="y" confirmLabel="Yes, delete"
        onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Yes, delete" })).toBeInTheDocument();
  });
});
