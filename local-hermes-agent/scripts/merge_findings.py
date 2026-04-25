#!/usr/bin/env python3
"""merge_findings.py — merge multiple audit JSON reports into findings-before.json.

Usage:
    python3 merge_findings.py <report1.json> [<report2.json> ...] --out <output.json>

Each input report must have a `findings` list with objects conforming to the audit finding schema.
The output file is sorted by (severity DESC, category ASC) and includes deferred overflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TOP_N = int(__import__("os").environ.get("AUDIT_TOP_N", "8"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _severity_key(finding: dict) -> tuple[int, str]:
    sev = finding.get("severity", "low").lower()
    cat = finding.get("category", "")
    return (SEVERITY_ORDER.get(sev, 99), cat)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge audit finding reports")
    parser.add_argument("inputs", nargs="+", help="Input JSON report files")
    parser.add_argument("--out", required=True, help="Output merged JSON path")
    args = parser.parse_args(argv)

    all_findings: list[dict] = []
    total_pass = 0
    total_fail = 0
    source_tags: list[str] = []

    for path_str in args.inputs:
        path = Path(path_str)
        if not path.exists():
            print(f"[merge_findings] warning: {path} does not exist; skipping", file=sys.stderr)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[merge_findings] warning: could not parse {path}: {exc}; skipping", file=sys.stderr)
            continue

        findings = data.get("findings") or []
        all_findings.extend(findings)
        total_pass += int(data.get("pass_count") or 0)
        total_fail += int(data.get("fail_count") or 0)
        tag = data.get("source_tag") or path.stem
        source_tags.append(tag)

    # De-duplicate by id (last writer wins if same id)
    seen_ids: dict[str, dict] = {}
    for f in all_findings:
        fid = f.get("id", "")
        seen_ids[fid] = f
    deduped = list(seen_ids.values())

    # Sort: critical/high first, then by category name
    deduped.sort(key=_severity_key)

    top_n = deduped[:TOP_N]
    deferred = deduped[TOP_N:]

    # Assign top-level sequential IDs to make Phase 2 routing unambiguous
    for i, finding in enumerate(top_n, start=1):
        finding["_rank"] = i
    for finding in deferred:
        finding["_deferred"] = True

    output = {
        "generated_at": _now(),
        "source_tags": source_tags,
        "total_findings": len(deduped),
        "top_n": TOP_N,
        "pass_count": total_pass,
        "fail_count": total_fail,
        "findings": top_n,
        "deferred": deferred,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"[merge_findings] merged {len(deduped)} findings ({len(top_n)} top, {len(deferred)} deferred) → {out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
