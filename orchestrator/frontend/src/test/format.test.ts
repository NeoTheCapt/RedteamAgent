import { describe, it, expect } from "vitest";
import { formatRelativeTime, severityColor, percentage, parseServerTimestamp } from "../lib/format";

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

describe("parseServerTimestamp", () => {
  it("returns null for empty / null / undefined", () => {
    expect(parseServerTimestamp("")).toBeNull();
    expect(parseServerTimestamp(null)).toBeNull();
    expect(parseServerTimestamp(undefined)).toBeNull();
  });

  it("parses ISO 8601", () => {
    const d = parseServerTimestamp("2026-04-17T12:00:00Z");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-04-17T12:00:00.000Z");
  });

  it("coerces SQLite timestamps to UTC ISO", () => {
    const d = parseServerTimestamp("2026-04-17 12:00:00");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-04-17T12:00:00.000Z");
  });

  it("returns null for garbage", () => {
    expect(parseServerTimestamp("not a date")).toBeNull();
  });
});
