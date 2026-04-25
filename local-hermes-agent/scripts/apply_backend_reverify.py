#!/usr/bin/env python3
"""Fold bounded-backend-restart re-verify results into findings-after.json.

After Phase 4 commits land, if the diff touched orchestrator/backend/**/*.py
run_cycle.sh restarts uvicorn and reruns the three prep scripts with a
`<cycle_id>-reverify` suffix. This helper compares those re-run artifacts
against findings previously marked `reverify_scope: pending_restart` and
flips each finding to either `runtime_restart_passed` (the failure no
longer appears after restart) or `runtime_restart_still_failing` (the
same failure is still present — the fix did not actually work, so the
finding is reopened for the next cycle).

Usage: apply_backend_reverify.py <cycle_id> <reverify_cycle_id>
  e.g. apply_backend_reverify.py 20260424T120000Z 20260424T120000Z-reverify

Exit codes:
  0 = ran cleanly (even if no findings changed)
  1 = I/O / schema error — something was dirty enough that run_cycle.sh
      should log it but not abort
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR_FMT = ROOT / "audit-reports" / "{cycle_id}"

# Which category is covered by which prep source; categories not in this map
# are considered non-runtime (agent_bug, agent_recall, orch_ui) and are left
# alone — those shouldn't have reverify_scope=pending_restart in the first
# place, but guard defensively.
CATEGORY_TO_SOURCE = {
    "orch_api":     "api.json",
    "orch_log":     "logs.json",
    "orch_feature": "features.json",
}


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[apply_backend_reverify] {path}: bad JSON — {exc}", file=sys.stderr)
        return None


def _endpoint(finding: dict) -> str | None:
    ev = finding.get("evidence") or {}
    if not isinstance(ev, dict):
        return None
    ep = ev.get("endpoint")
    return ep.strip() if isinstance(ep, str) and ep.strip() else None


def _failure_still_present(finding: dict, reverify_doc: dict) -> bool:
    """Heuristic match: look up the auditor finding in the reverify prep doc.

    Primary key: `evidence.endpoint` equality (strong signal for api.json).
    Secondary key: finding id equality (e.g. `API-001` — the auditor usually
    reuses the prep source id verbatim).
    """
    if not isinstance(reverify_doc, dict):
        return False
    entries = reverify_doc.get("findings") or []
    if not isinstance(entries, list):
        return False

    ep = _endpoint(finding)
    fid = finding.get("id")

    for e in entries:
        if not isinstance(e, dict):
            continue
        # Endpoint match (when present on both sides)
        re_ep = _endpoint(e)
        if ep and re_ep and ep == re_ep:
            return True
        # ID match — auditor typically reuses prep source ids (API-001, LOG-001, …)
        if fid and e.get("id") == fid:
            return True
    return False


def process(cycle_id: str, reverify_cycle_id: str) -> int:
    audit_dir = Path(str(AUDIT_DIR_FMT).replace("{cycle_id}", cycle_id))
    reverify_dir = Path(str(AUDIT_DIR_FMT).replace("{cycle_id}", reverify_cycle_id))

    after_path = audit_dir / "findings-after.json"
    if not after_path.exists():
        print(f"[apply_backend_reverify] {after_path} missing; nothing to do",
              file=sys.stderr)
        return 0

    after_doc = load_json(after_path)
    if after_doc is None:
        return 1

    # Load reverify prep docs lazily (category-keyed).
    reverify_cache: dict[str, dict | None] = {}

    def reverify_for(category: str):
        source = CATEGORY_TO_SOURCE.get(category)
        if not source:
            return None
        if source in reverify_cache:
            return reverify_cache[source]
        reverify_cache[source] = load_json(reverify_dir / source)
        return reverify_cache[source]

    changed = 0
    flipped_passed = 0
    flipped_failing = 0

    def handle_bucket(items: list):
        nonlocal changed, flipped_passed, flipped_failing
        if not isinstance(items, list):
            return
        for f in items:
            if not isinstance(f, dict):
                continue
            if (f.get("reverify_scope") or "").strip() != "pending_restart":
                continue
            cat = f.get("category") or ""
            re_doc = reverify_for(cat)
            if re_doc is None:
                # No reverify data for this category — leave the finding as-is
                # and surface a note. Do NOT flip without evidence.
                f.setdefault("notes", [])
                if isinstance(f["notes"], list):
                    f["notes"].append(
                        f"apply_backend_reverify: no {CATEGORY_TO_SOURCE.get(cat, cat)} "
                        "in reverify run; scope unchanged"
                    )
                continue

            still_failing = _failure_still_present(f, re_doc)
            if still_failing:
                f["reverify_scope"] = "runtime_restart_still_failing"
                # The fix did NOT actually work under the refreshed runtime.
                # Reopen so the next cycle's persistent-bug rule takes it up
                # with elevated severity.
                if f.get("status") == "fixed":
                    f["status"] = "open"
                    f.setdefault("reason", "bounded backend restart re-verify: "
                                 "same failure still present")
                flipped_failing += 1
            else:
                f["reverify_scope"] = "runtime_restart_passed"
                flipped_passed += 1
            changed += 1

    handle_bucket(after_doc.get("findings") or [])
    handle_bucket(after_doc.get("deferred") or [])

    if changed:
        after_path.write_text(
            json.dumps(after_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        f"[apply_backend_reverify] cycle={cycle_id} changed={changed} "
        f"passed={flipped_passed} still_failing={flipped_failing}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle_id")
    parser.add_argument("reverify_cycle_id",
                        help="typically `<cycle_id>-reverify`")
    args = parser.parse_args(argv)
    return process(args.cycle_id, args.reverify_cycle_id)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
