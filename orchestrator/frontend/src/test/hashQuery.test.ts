import { describe, it, expect } from "vitest";
import { parseHashQuery, encodeHashQuery } from "../lib/hashQuery";

describe("parseHashQuery", () => {
  it("returns empty query for path without ?", () => {
    expect(parseHashQuery("#/a/b")).toEqual({ path: "/a/b", query: {} });
  });

  it("parses simple key=value pairs", () => {
    expect(parseHashQuery("#/x?a=1&b=2")).toEqual({
      path: "/x",
      query: { a: "1", b: "2" },
    });
  });

  it("decodes percent-encoded values", () => {
    expect(parseHashQuery("#/x?q=hello%20world")).toEqual({
      path: "/x",
      query: { q: "hello world" },
    });
  });

  it("accepts missing =", () => {
    expect(parseHashQuery("#/x?flag")).toEqual({
      path: "/x",
      query: { flag: "" },
    });
  });

  it("handles hash without leading #", () => {
    expect(parseHashQuery("/x?a=1")).toEqual({ path: "/x", query: { a: "1" } });
  });
});

describe("encodeHashQuery", () => {
  it("returns path when query empty", () => {
    expect(encodeHashQuery("/x", {})).toBe("/x");
  });

  it("encodes values", () => {
    expect(encodeHashQuery("/x", { q: "hello world" })).toBe("/x?q=hello%20world");
  });

  it("drops undefined + empty values", () => {
    expect(encodeHashQuery("/x", { a: "1", b: undefined, c: "" })).toBe("/x?a=1");
  });

  it("roundtrips", () => {
    const encoded = encodeHashQuery("/p", { state: "finding", method: "GET" });
    const parsed = parseHashQuery("#" + encoded);
    expect(parsed.path).toBe("/p");
    expect(parsed.query).toEqual({ state: "finding", method: "GET" });
  });
});
