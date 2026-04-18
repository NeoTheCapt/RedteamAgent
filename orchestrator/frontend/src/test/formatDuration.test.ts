import { describe, it, expect } from "vitest";
import { formatDuration, formatDurationSince } from "../lib/formatDuration";

describe("formatDuration", () => {
  it("returns dash for null/undefined", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
  it("sub-second as ms", () => {
    expect(formatDuration(250)).toBe("250ms");
  });
  it("second range", () => {
    expect(formatDuration(1500)).toBe("1.5s");
  });
  it("minutes + seconds", () => {
    expect(formatDuration(125000)).toBe("2m 5s");
  });
  it("hours + minutes", () => {
    expect(formatDuration(3900000)).toBe("1h 5m");
  });
  it("exact minute rounds correctly", () => {
    expect(formatDuration(60000)).toBe("1m 0s");
    expect(formatDuration(61000)).toBe("1m 1s");
  });
});

describe("formatDurationSince", () => {
  it("empty when startedSec is null", () => {
    expect(formatDurationSince(null)).toBe("");
  });
  it("computes a live duration when endedSec is null", () => {
    const now = Math.floor(Date.now() / 1000);
    // Started 10 seconds ago
    const result = formatDurationSince(now - 10);
    // Will be "10.0s" or "9.0s" depending on rounding; allow either
    expect(result).toMatch(/^(9|10|11)(\.\d)?s$/);
  });
  it("uses endedSec when provided", () => {
    expect(formatDurationSince(1000, 1065)).toBe("1m 5s");
  });
});
