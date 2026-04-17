import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { TabNav } from "../components/shell/TabNav";

describe("TabNav", () => {
  it("advances selection on ArrowRight", async () => {
    const onSelect = vi.fn();
    render(<TabNav current="dashboard" onSelect={onSelect} />);
    const dashboardTab = screen.getByRole("tab", { name: /Dashboard/i });
    dashboardTab.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onSelect).toHaveBeenCalledWith("progress");
  });

  it("wraps on ArrowLeft from the first tab", async () => {
    const onSelect = vi.fn();
    render(<TabNav current="dashboard" onSelect={onSelect} />);
    screen.getByRole("tab", { name: /Dashboard/i }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onSelect).toHaveBeenCalledWith("events");
  });

  it("jumps to last tab on End", async () => {
    const onSelect = vi.fn();
    render(<TabNav current="cases" onSelect={onSelect} />);
    screen.getByRole("tab", { name: /Cases/i }).focus();
    await userEvent.keyboard("{End}");
    expect(onSelect).toHaveBeenCalledWith("events");
  });

  it("exposes aria-controls + aria-labelledby ids", () => {
    render(<TabNav current="progress" onSelect={vi.fn()} />);
    const progressTab = screen.getByRole("tab", { name: /Progress/i });
    expect(progressTab).toHaveAttribute("id", "tab-progress");
    expect(progressTab).toHaveAttribute("aria-controls", "tabpanel-progress");
    expect(progressTab).toHaveAttribute("aria-selected", "true");
    expect(progressTab).toHaveAttribute("tabIndex", "0");
    const dashboardTab = screen.getByRole("tab", { name: /Dashboard/i });
    expect(dashboardTab).toHaveAttribute("tabIndex", "-1");
  });
});
