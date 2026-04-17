import { describe, it, expect, beforeAll } from "vitest";

// We load tokens.css into JSDOM at test time and check the computed CSS variables
// resolve on :root. This catches typos, accidental removal, and scale regressions.

beforeAll(async () => {
  const tokens = await import("../styles/tokens.css?raw" as string);
  const style = document.createElement("style");
  // Strip the @import (rsms.me) because JSDOM can't fetch it. Token vars remain.
  style.textContent = tokens.default.replace(/@import[^;]+;/g, "");
  document.head.appendChild(style);
});

describe("design tokens", () => {
  const root = () => getComputedStyle(document.documentElement);

  it("defines the font-size scale with integer px values", () => {
    const scale: [string, string][] = [
      ["--fs-xs", "11px"],
      ["--fs-sm", "12px"],
      ["--fs-md", "13px"],
      ["--fs-base", "14px"],
      ["--fs-lg", "16px"],
      ["--fs-xl", "18px"],
      ["--fs-2xl", "20px"],
      ["--fs-3xl", "24px"],
      ["--fs-num", "30px"],
      ["--fs-bignum", "36px"],
    ];
    for (const [name, expected] of scale) {
      expect(root().getPropertyValue(name).trim()).toBe(expected);
    }
  });

  it("exposes UI and mono font stacks", () => {
    expect(root().getPropertyValue("--font-ui")).toMatch(/Inter/);
    expect(root().getPropertyValue("--font-mono")).toMatch(/JetBrains Mono/);
  });

  it("exposes line-height tokens", () => {
    expect(root().getPropertyValue("--lh-body").trim()).toBe("1.5");
    expect(root().getPropertyValue("--lh-heading").trim()).toBe("1.3");
    expect(root().getPropertyValue("--lh-dense").trim()).toBe("1.25");
  });
});
