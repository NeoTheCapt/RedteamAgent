#!/usr/bin/env python3
"""Validate a cycle's output artifacts against the contract the auditor
agent is supposed to produce. Run after Phase 4 to catch dirty data
before it reaches the operator.

Contract (F4 — artifact schema validation):
  1. findings-after.json: every finding `id` appears exactly once (merging
     both `findings` and `deferred` arrays). Each record has a non-empty
     `summary`, a valid `status`, and — if present — a fingerprint that
     matches `<category>-<12 hex>`.
  2. source-status.json.orch_ui.checks: exactly 12 entries with stable
     check_ids ui-01..ui-12. Every entry whose `result == "passed"` must
     reference an existing screenshot file under ui-screenshots/.
  3. Every commit message in `<baseline_sha>..HEAD` whose subject has
     `FND-XXX` references a finding id that actually exists in
     findings-before.json for this cycle.
  4. Fingerprint format: if any finding has a `fingerprint` field, it
     must match the regex `^[a-z_]+-[0-9a-f]{12}$`.

Exit code 0 = clean; non-zero = violations (details printed to stderr).

Usage: validate_cycle_artifacts.py <cycle_id> [--baseline-sha <sha>]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
AUDIT_DIR_FMT = ROOT / "audit-reports" / "{cycle_id}"

FINGERPRINT_RE = re.compile(r"^[a-z_]+-[0-9a-f]{12}$")
FND_RE = re.compile(r"\b(FND-\d+|PERSIST-\d+)\b")
VALID_STATUSES = {"open", "fixed", "deferred", "reclassified", "skipped"}
EXPECTED_CHECK_IDS = {f"ui-{i:02d}" for i in range(1, 13)}


class Violations:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def __bool__(self) -> bool:
        return bool(self.items)

    def print_report(self) -> None:
        if not self.items:
            print("[validate] all checks passed", file=sys.stderr)
            return
        print(f"[validate] {len(self.items)} violation(s):", file=sys.stderr)
        for m in self.items:
            print(f"  - {m}", file=sys.stderr)


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__load_error__": str(exc)}


def check_findings_after(audit_dir: Path, v: Violations) -> dict[str, dict]:
    """Return id→record map so the commit-msg check can reuse it."""
    doc = load_json(audit_dir / "findings-after.json")
    if not doc:
        v.add("findings-after.json missing or empty")
        return {}
    if isinstance(doc.get("__load_error__"), str):
        v.add(f"findings-after.json is not valid JSON: {doc['__load_error__']}")
        return {}

    seen: dict[str, dict] = {}
    records = list(doc.get("findings") or []) + list(doc.get("deferred") or [])
    for r in records:
        fid = r.get("id")
        if not fid:
            v.add("finding entry with no id in findings-after.json")
            continue
        if fid in seen:
            # Duplicate — B2 contract violation.
            v.add(
                f"finding id {fid} appears twice in findings-after.json "
                f"(first record status={seen[fid].get('status')}, "
                f"second record status={r.get('status')})"
            )
            # Prefer the meatier record for downstream checks.
            prev = seen[fid]
            if not (prev.get("summary") or "").strip() and (r.get("summary") or "").strip():
                seen[fid] = r
            continue
        seen[fid] = r

    for fid, r in seen.items():
        status = r.get("status")
        if status not in VALID_STATUSES:
            v.add(f"finding {fid} has invalid status {status!r} (allowed: {sorted(VALID_STATUSES)})")
        if not (r.get("summary") or "").strip():
            v.add(f"finding {fid} has empty summary")
        fp = r.get("fingerprint")
        if fp is not None and not FINGERPRINT_RE.match(str(fp)):
            v.add(f"finding {fid} has malformed fingerprint {fp!r} (expected <category>-<12 hex>)")
    return seen


def check_source_status(audit_dir: Path, v: Violations) -> None:
    doc = load_json(audit_dir / "source-status.json")
    if not doc:
        # Legitimate when the skill didn't run (agent session interrupted).
        v.add("source-status.json missing (agent did not write Phase 1 checkpoint)")
        return

    ui = doc.get("orch_ui") or {}
    checks = ui.get("checks") or []
    if not checks:
        v.add("source-status.json.orch_ui.checks is empty (agent didn't walk UI checks)")
        return

    check_ids = {c.get("check_id") for c in checks}
    missing = sorted(EXPECTED_CHECK_IDS - check_ids)
    extra = sorted(check_ids - EXPECTED_CHECK_IDS - {None})
    if missing:
        v.add(f"source-status.json.orch_ui.checks missing check_ids: {missing}")
    if extra:
        v.add(f"source-status.json.orch_ui.checks has unexpected check_ids: {extra}")

    for c in checks:
        cid = c.get("check_id") or "?"
        result = c.get("result") or ""
        if result == "passed":
            screenshot = c.get("screenshot") or ""
            if not screenshot:
                v.add(f"check {cid} result=passed but no screenshot path")
            else:
                ss_path = audit_dir / screenshot if not screenshot.startswith("/") else Path(screenshot)
                # Allow relative paths resolved against audit_dir.
                candidate = ss_path if ss_path.exists() else audit_dir / screenshot
                if not candidate.exists():
                    v.add(f"check {cid} result=passed but screenshot {screenshot} not found on disk")


def check_commit_message_finding_ids(
    audit_dir: Path, baseline_sha: str | None, v: Violations
) -> None:
    before = load_json(audit_dir / "findings-before.json") or {}
    before_ids: set[str] = set()
    for r in (before.get("findings") or []) + (before.get("deferred") or []):
        fid = r.get("id")
        if fid:
            before_ids.add(fid)

    if not baseline_sha:
        # Can't know the commit range; skip this check (soft).
        return

    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "log", "--format=%H %s",
             f"{baseline_sha}..HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        v.add(f"git log failed for range {baseline_sha}..HEAD: {exc}")
        return

    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        for match in FND_RE.finditer(subject):
            token = match.group(1)
            if token not in before_ids:
                v.add(
                    f"commit {sha[:7]} subject references {token} "
                    f"but findings-before.json has no such id "
                    f"(known: {sorted(before_ids) or 'none'})"
                )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle_id")
    parser.add_argument("--baseline-sha", default=None,
                        help="Commit to anchor the review range. If omitted, commit-msg check is skipped.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero on any violation (default).")
    args = parser.parse_args(argv)

    audit_dir = Path(str(AUDIT_DIR_FMT).replace("{cycle_id}", args.cycle_id))
    if not audit_dir.exists():
        print(f"[validate] audit dir missing: {audit_dir}", file=sys.stderr)
        return 2

    v = Violations()
    check_findings_after(audit_dir, v)
    check_source_status(audit_dir, v)
    check_commit_message_finding_ids(audit_dir, args.baseline_sha, v)

    v.print_report()
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
