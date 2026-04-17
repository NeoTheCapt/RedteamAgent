import { describe, it, expect } from "vitest";
import { formatDurationMs, formatRelativeTime, severityColor, percentage } from "../lib/format";

describe("formatDurationMs", () => {
  it("returns dash for null", () => { expect(formatDurationMs(null)).toBe("—"); });
  it("returns dash for undefined", () => { expect(formatDurationMs(undefined)).toBe("—"); });
  it("formats sub-second as ms", () => { expect(formatDurationMs(250)).toBe("250ms"); });
  it("formats seconds", () => { expect(formatDurationMs(2500)).toBe("2.5s"); });
  it("formats minutes + seconds", () => { expect(formatDurationMs(125000)).toBe("2m 5s"); });
  it("formats hours + minutes", () => { expect(formatDurationMs(3900000)).toBe("1h 5m"); });
});

describe("formatRelativeTime", () => {
  const now = Date.parse("2026-04-17T12:00:00Z");
  it("handles sub-minute", () => {
    expect(formatRelativeTime("2026-04-17T11:59:30Z", now)).toBe("30s ago");
  });
  it("handles minutes", () => {
    expect(formatRelativeTime("2026-04-17T11:55:00Z", now)).toBe("5m ago");
  });
  it("handles hours", () => {
    expect(formatRelativeTime("2026-04-17T10:00:00Z", now)).toBe("2h ago");
  });
  it("handles days", () => {
    expect(formatRelativeTime("2026-04-15T12:00:00Z", now)).toBe("2d ago");
  });
  it("returns dash for bad input", () => {
    expect(formatRelativeTime("not-a-date")).toBe("—");
  });
});

describe("severityColor", () => {
  it("maps critical→red", () => {
    expect(severityColor("critical")).toBe("var(--c-red)");
  });
  it("is case-insensitive", () => {
    expect(severityColor("CRITICAL")).toBe("var(--c-red)");
  });
  it("falls back for unknown", () => {
    expect(severityColor("bogus")).toBe("var(--c-text-dim)");
  });
  it("handles null", () => {
    expect(severityColor(null)).toBe("var(--c-text-dim)");
  });
  it("handles undefined", () => {
    expect(severityColor(undefined)).toBe("var(--c-text-dim)");
  });
});

describe("percentage", () => {
  it("rounds to whole percent", () => {
    expect(percentage(1, 3)).toBe("33%");
  });
  it("guards against divide by zero", () => {
    expect(percentage(5, 0)).toBe("0%");
  });
  it("computes exact values", () => {
    expect(percentage(50, 100)).toBe("50%");
  });
});
