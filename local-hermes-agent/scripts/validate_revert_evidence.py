#!/usr/bin/env python3
"""Revert cooling-off validator.

When this cycle's diff deletes lines that were added by a prior
`fix(audit-*)` commit (already detected and listed by F2 regression
check), the motivation for the revert must be backed by CONCRETE evidence
— not prose reasoning. Cycles 20260423T144908Z..20260424T051159Z showed
a 4-step flip-flop between parallel and serialized consume-test dispatch
rules, each audit undoing the prior one on plausible-sounding but
evidence-free grounds.

This validator fails the cycle (flags `success_with_dirty_artifacts`
without aborting commits) when:
  - The current cycle's commits include at least one revert of prior
    `fix(audit-*)` lines (per cross-cycle-regression.json).
  - A finding in findings-after.json has `status == "fixed"` and its
    `commit` falls within the current cycle's range.
  - That finding does NOT provide `evidence.regression_evidence` with
    concrete data (benchmark cycle id where metric regressed, failing
    test output, engagement log path:line, or case-db ERROR outcome).

Concrete-evidence shapes that pass (any ONE is sufficient, and the field
must be non-empty after trim):
  - regression_evidence.recall_drop_cycle   — cycle_id string
  - regression_evidence.failing_test        — path to test output file + summary
  - regression_evidence.log_tail            — "<path>:<line>" ref
  - regression_evidence.case_outcome        — cases.db case id + outcome row

Prose-only entries (e.g. `"regression_evidence": "parallel dispatch
displaced serialized rule"`) are considered insufficient — the whole
point is to break the flip-flop by requiring a real data point.

Usage:
    python3 validate_revert_evidence.py <cycle_id> [--baseline-sha SHA]

Exit codes:
    0 — no reverts detected OR every revert has sufficient evidence
    1 — at least one revert lacks concrete regression evidence (violations
        printed to stderr; caller flags cycle dirty)
    2 — missing input files / internal error
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
FND_RE = re.compile(r"\b(FND-\d+|PERSIST-\d+|VA-\d+|EX-\d+|SA-\d+|RE-\d+|FZ-\d+|OS-\d+)\b")
# minimum char length for a concrete-evidence value to count as non-trivial.
MIN_EVIDENCE_LEN = 5


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cycle_commit_subjects(baseline: str | None) -> dict[str, str]:
    """Return {short_sha: subject} for every commit in baseline..HEAD."""
    if not baseline:
        return {}
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%h %s", f"{baseline}..HEAD"],
            cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return {}
    result = {}
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if sha:
            result[sha] = subject
    return result


def has_concrete_evidence(field) -> bool:
    """Accept dict with at least one non-empty concrete key, or a plain
    string that obviously looks like a reference (colon-separated path:line,
    starts with 20260 cycle id, or contains 'pass=' / 'fail=')."""
    if isinstance(field, dict):
        for key in ("recall_drop_cycle", "failing_test", "log_tail", "case_outcome"):
            v = field.get(key)
            if isinstance(v, str) and len(v.strip()) >= MIN_EVIDENCE_LEN:
                return True
            if isinstance(v, dict) and any(isinstance(vv, str) and vv.strip() for vv in v.values()):
                return True
        return False
    if isinstance(field, str):
        s = field.strip()
        if len(s) < MIN_EVIDENCE_LEN:
            return False
        # Plausible-reference heuristics.
        if re.search(r":\d+", s):
            return True
        if s.startswith("2026") or s.startswith("cycle "):
            return True
        if "pass=" in s or "fail=" in s or "ERROR" in s:
            return True
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle_id")
    parser.add_argument("--baseline-sha", default=None,
                        help="required for resolving the cycle's commit range")
    args = parser.parse_args(argv)

    audit_dir = Path(str(AUDIT_DIR_FMT).replace("{cycle_id}", args.cycle_id))
    if not audit_dir.exists():
        print(f"[revert-evidence] audit dir missing: {audit_dir}", file=sys.stderr)
        return 2

    regression_json = audit_dir / "cross-cycle-regression.json"
    # The F2 script now emits this when the run_cycle.sh wrapper passes --json-out.
    # If it isn't present, the validator falls back to "no reverts detected" — this
    # is safe (we only escalate on positive evidence of a revert).
    reg = load_json(regression_json)
    prior_shas = set((reg or {}).get("prior_commit_shas") or [])
    if not prior_shas:
        print("[revert-evidence] no reverts detected by F2; nothing to validate",
              file=sys.stderr)
        return 0

    after_path = audit_dir / "findings-after.json"
    after = load_json(after_path)
    if after is None:
        print(f"[revert-evidence] findings-after.json missing at {after_path}", file=sys.stderr)
        return 2

    commits = cycle_commit_subjects(args.baseline_sha)
    if not commits:
        print("[revert-evidence] no commits in cycle range (nothing to validate)",
              file=sys.stderr)
        return 0

    # Map finding id → commit sha using commit subject tokens + the finding's
    # own `commit` field as a fallback.
    id_to_commit: dict[str, str] = {}
    for sha, subject in commits.items():
        for match in FND_RE.finditer(subject):
            id_to_commit.setdefault(match.group(1), sha)

    violations: list[str] = []
    for f in (after.get("findings") or []) + (after.get("deferred") or []):
        if not isinstance(f, dict):
            continue
        if f.get("status") != "fixed":
            continue
        fid = f.get("id") or "?"
        finding_sha = (f.get("commit") or id_to_commit.get(fid) or "").strip()
        if not finding_sha or finding_sha[:7] not in {s[:7] for s in commits}:
            continue

        # Does this commit actually revert prior audit lines? The F2 data
        # tells us which prior_shas had lines removed by the cycle as a
        # whole; we cannot trivially pin a deleted line to a specific cycle
        # commit, so we treat every fixed finding inside a revert-flagged
        # cycle as subject to the evidence requirement. This is the correct
        # conservative stance: when F2 shows the cycle reverted prior audit
        # work, every fix in the cycle needs evidence grounding to rule out
        # flip-flop churn.
        ev = f.get("evidence") or {}
        ev_re = None
        if isinstance(ev, dict):
            ev_re = ev.get("regression_evidence")
        top_re = f.get("regression_evidence")
        if not (has_concrete_evidence(ev_re) or has_concrete_evidence(top_re)):
            reverted_shas = ", ".join(sorted(prior_shas))
            violations.append(
                f"finding {fid} (commit {finding_sha[:7]}) is `fixed` inside a "
                f"cycle that reverted prior audit commit(s) [{reverted_shas}] "
                "but carries no `evidence.regression_evidence` with concrete "
                "data (recall_drop_cycle / failing_test / log_tail / "
                "case_outcome). Revert cooling-off: demote this finding to "
                "`deferred` until concrete regression evidence is recorded."
            )

    if not violations:
        print(
            f"[revert-evidence] cycle reverted {len(prior_shas)} prior audit "
            f"commit(s); all fixed findings carry regression_evidence",
            file=sys.stderr,
        )
        return 0

    print(f"[revert-evidence] {len(violations)} violation(s):", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
