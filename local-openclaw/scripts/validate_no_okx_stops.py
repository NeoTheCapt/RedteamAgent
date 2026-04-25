#!/usr/bin/env python3
"""Detect ui-07 stopping the okx run, fail the cycle dirty if so.

Cycles 20260425T054522Z..111827Z each ran ui-07 against the running okx
target — 7 consecutive okx runs (#678..#709) were `user_stopped` by
auditor browser sessions, and the okx target was never in steady state.
The skill now tells Hermes to pick a non-okx run for ui-07, but skill
text is advisory; this script enforces.

Logic:
  - List all runs whose target ends in `okx.com`
  - For each, if its `ended_at` falls within this cycle's window AND
    `stop_reason_code == 'user_stopped'` → violation
  - Cycle window = controller.log first/last timestamps, or fall back
    to baseline_sha commit time + cycle_id timestamp (ISO from cycle id)

Exit 0 = clean (no okx stops in window), 1 = violation, 2 = data missing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    # Orchestrator stores datetimes as `YYYY-MM-DD HH:MM:SS` without
    # timezone — assume UTC since the rest of the cycle uses UTC.
    if " " in s and "+" not in s and "T" not in s:
        s = s.replace(" ", "T") + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def cycle_window_from_id(cycle_id: str) -> datetime | None:
    """Cycle id like 20260425T111827Z encodes the start time directly."""
    m = re.match(r"^(\d{8})T(\d{6})Z$", cycle_id)
    if not m:
        return None
    return datetime.strptime(m.group(0), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def fetch_runs() -> list[dict]:
    env_file = REPO_ROOT / "local-openclaw" / "state" / "scheduler.env"
    token = ""
    base_url = ""
    project_id = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ORCH_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("ORCH_BASE_URL="):
                base_url = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("PROJECT_ID="):
                project_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    base_url = base_url or "http://127.0.0.1:18000"
    project_id = project_id or "19"
    if not token:
        raise RuntimeError("ORCH_TOKEN missing")
    req = urllib.request.Request(
        f"{base_url}/projects/{project_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycle_id")
    parser.add_argument("--window-pad-min", type=int, default=2,
                        help="Pad the cycle window by N minutes on each side (default 2)")
    parser.add_argument("--protected-suffix", default="okx.com",
                        help="Target suffix that must not be stopped (default okx.com)")
    args = parser.parse_args(argv)

    start = cycle_window_from_id(args.cycle_id)
    if start is None:
        print(f"[no-okx-stops] cannot parse cycle_id {args.cycle_id!r}", file=sys.stderr)
        return 2

    # Cycle ends ~30 min after start; pad both ends.
    pad = timedelta(minutes=args.window_pad_min)
    cycle_start = start - pad
    cycle_end = start + timedelta(minutes=30) + pad

    try:
        runs = fetch_runs()
    except Exception as exc:
        print(f"[no-okx-stops] cannot fetch runs: {exc}", file=sys.stderr)
        return 2

    suffix = args.protected_suffix.lower()
    violations = []
    for r in runs:
        target = (r.get("target") or "").lower()
        if not target.endswith(suffix):
            continue
        if r.get("stop_reason_code") != "user_stopped":
            continue
        ended = parse_iso(r.get("ended_at") or "")
        if ended is None:
            continue
        if cycle_start <= ended <= cycle_end:
            violations.append({
                "run_id": r.get("id"),
                "target": r.get("target"),
                "ended_at": r.get("ended_at"),
                "stop_reason_text": r.get("stop_reason_text"),
            })

    if not violations:
        print(
            f"[no-okx-stops] no {args.protected_suffix} runs stopped in cycle window",
            file=sys.stderr,
        )
        return 0

    print(
        f"[no-okx-stops] {len(violations)} violation(s): {args.protected_suffix} "
        f"run(s) stopped within cycle window — likely ui-07 targeting wrong run.",
        file=sys.stderr,
    )
    for v in violations:
        print(
            f"  - run {v['run_id']} target={v['target']} ended={v['ended_at']} "
            f"reason='{v.get('stop_reason_text')}'",
            file=sys.stderr,
        )
    print(
        "  ACTION: ui-07 must target the non-okx (Juice Shop) run. The skill rule "
        "in redteam-auditor-hermes/SKILL.md spells this out; either Hermes is "
        "reading a stale cached skill OR the rule needs reinforcement in the "
        "loop prompt.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
