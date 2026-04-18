import { describe, it, expect, vi } from "vitest";
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
    vi.useFakeTimers();
    vi.setSystemTime(new Date(10_000_000));  // 10_000 sec
    expect(formatDurationSince(9990)).toBe("10.0s");
    vi.useRealTimers();
  });
  it("uses endedSec when provided", () => {
    expect(formatDurationSince(1000, 1065)).toBe("1m 5s");
  });
});
