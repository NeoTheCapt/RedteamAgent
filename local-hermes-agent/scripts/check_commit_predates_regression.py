#!/usr/bin/env python3
"""Timeline sanity check: did this commit land BEFORE the recall regression
it claims to have caused?

Runs during Phase 2 when Hermes is about to attribute a recall regression to
a specific prior commit. The prior cycle 20260424T041427Z committed 5793ded
claiming that 8abdab7 (Apr 23) caused a recall drop from 0.117 to 0.036 —
but that drop happened on Apr 13, a full 10 days before 8abdab7 existed.
Hermes satisfied "investigate root cause" with shallow correlation instead
of checking commit dates.

This script fails loudly whenever a suspect commit POSTDATES the regression
event, preventing that class of confabulation.

Usage:
    python3 check_commit_predates_regression.py \\
        --commit <sha> \\
        --target <url> \\
        [--history-file <path>]

Exit codes:
    0 — commit predates the regression (plausible cause)
    1 — commit POSTDATES the regression (cannot be the cause; pick another)
    2 — insufficient data (missing commit, missing history, no drop event)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY = REPO_ROOT / "local-hermes-agent" / "state" / "benchmark-metrics-history.json"


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def commit_date(sha: str) -> datetime | None:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI", sha],
            cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return parse_iso(out)


def find_first_drop(history: list[dict]) -> tuple[dict, dict] | None:
    """Return (peak_record, first_drop_record) or None if no drop occurred.

    The drop event is the first history entry where recall is strictly below
    the running max. Records with missing/non-numeric recall are skipped.
    """
    def _r(rec: dict) -> float | None:
        m = rec.get("metrics") or {}
        v = m.get("challenge_recall")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    peak = None
    for rec in history:
        r = _r(rec)
        if r is None:
            continue
        if peak is None or r > (peak_r := _r(peak) or 0.0):
            peak = rec
            continue
        if r < (_r(peak) or 0.0):
            return (peak, rec)
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True,
                        help="suspect commit SHA that Hermes thinks caused the regression")
    parser.add_argument("--target", required=True,
                        help="target URL key under benchmark-metrics-history.json.targets")
    parser.add_argument("--history-file", default=str(DEFAULT_HISTORY))
    args = parser.parse_args(argv)

    sha = args.commit.strip()
    target = args.target.strip()
    hist_path = Path(args.history_file)

    commit_iso = commit_date(sha)
    if commit_iso is None:
        print(f"[timeline-check] BLOCKED: git cannot resolve commit {sha!r}", file=sys.stderr)
        return 2

    if not hist_path.exists():
        print(f"[timeline-check] BLOCKED: no history at {hist_path}", file=sys.stderr)
        return 2

    try:
        doc = json.loads(hist_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[timeline-check] BLOCKED: history parse error — {exc}", file=sys.stderr)
        return 2

    tgt = (doc.get("targets") or {}).get(target)
    if not tgt:
        print(f"[timeline-check] BLOCKED: no target {target!r} in history", file=sys.stderr)
        return 2

    history = tgt.get("history") or []
    drop = find_first_drop(history)
    if drop is None:
        print(f"[timeline-check] no recall regression recorded for {target!r}; nothing to check",
              file=sys.stderr)
        return 0

    peak_rec, drop_rec = drop
    drop_time = parse_iso(drop_rec.get("updated_at") or "")
    if drop_time is None:
        print(f"[timeline-check] BLOCKED: drop event has no parseable updated_at", file=sys.stderr)
        return 2

    def _r(rec):
        try: return float(((rec.get("metrics") or {}).get("challenge_recall") or "0"))
        except (TypeError, ValueError): return 0.0

    summary_lines = [
        f"suspect commit:    {sha}  @  {commit_iso.isoformat()}",
        f"peak recall:       {_r(peak_rec):.3f}  in cycle {peak_rec.get('cycle_id')} @ {peak_rec.get('updated_at')}",
        f"first drop below:  {_r(drop_rec):.3f}  in cycle {drop_rec.get('cycle_id')} @ {drop_rec.get('updated_at')}",
    ]

    if commit_iso <= drop_time:
        print("[timeline-check] OK: suspect commit predates the recall drop; plausible cause",
              file=sys.stderr)
        for ln in summary_lines:
            print(f"  {ln}", file=sys.stderr)
        return 0

    delta = commit_iso - drop_time
    print(
        "[timeline-check] BLOCKED: suspect commit POSTDATES the recall drop "
        f"by {delta.days}d{delta.seconds//3600}h — it cannot be the cause.",
        file=sys.stderr,
    )
    for ln in summary_lines:
        print(f"  {ln}", file=sys.stderr)
    print("  ACTION: pick a commit that predates the drop, or acknowledge that the "
          "regression has no single-commit cause and is a pre-existing baseline issue.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
