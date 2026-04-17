import { describe, it, expect } from "vitest";
import type { Case, Dispatch, DocumentEntry, DocumentTree, RunSummary } from "../lib/api";

describe("api types", () => {
  it("RunSummary has dispatches and cases aggregates", () => {
    const sample: RunSummary["dispatches"] = { total: 0, active: 0, done: 0, failed: 0 };
    const samp2: RunSummary["cases"] = {
      total: 0, done: 0, running: 0, queued: 0, error: 0, findings: 0,
    };
    expect(sample.total).toBe(0);
    expect(samp2.findings).toBe(0);
  });

  it("Dispatch and Case shapes compile", () => {
    const d: Dispatch = {
      id: "B-1", phase: "consume", round: 1, agent: "v", slot: "0",
      task: null, state: "running", started_at: null, finished_at: null, error: null,
    };
    const c: Case = {
      case_id: 1, method: "GET", path: "/x", category: null, dispatch_id: "B-1",
      state: "queued", result: null, finding_id: null,
      started_at: null, finished_at: null, duration_ms: null,
    };
    expect(d.id).toBe("B-1");
    expect(c.case_id).toBe(1);
  });

  it("DocumentTree has 5 buckets", () => {
    const tree: DocumentTree = {
      findings: [], reports: [], intel: [], surface: [], other: [],
    };
    const entry: DocumentEntry = { name: "x", path: "x", size: 0, mtime: 0 };
    tree.findings.push(entry);
    expect(Object.keys(tree)).toEqual(["findings", "reports", "intel", "surface", "other"]);
  });
});
