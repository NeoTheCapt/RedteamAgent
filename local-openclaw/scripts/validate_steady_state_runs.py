#!/usr/bin/env python3
"""Enforce the steady-state contract: every fixed target must have at
least one `running` run at cycle end.

ui-07 STOP transition is allowed to stop ANY run during the audit, but
the cycle must NOT leave a fixed target (okx.com, 127.0.0.1:8000) with
zero running runs. The auditor must either pick a redundant run or
spawn a replacement via POST /runs immediately after the STOP click.

This validator runs at cycle end. For each fixed target, it counts
running runs in the orchestrator. If the count is zero, that's a
contract violation — the auditor stopped a sole-runner without
spawning a replacement.

Why "steady-state" rather than "okx is forbidden":
  - ui-07 STILL needs to test the STOP UI; banning targets just moves
    the problem around (whichever target IS allowed gets thrashed).
  - The real invariant the operator wants is "always ≥1 running per
    target", not "ui-07 must never click STOP on okx".
  - This semantic also catches non-ui-07 stops (e.g. a future skill
    that stops runs for a different reason) without naming targets.

Cycles 20260425T054522Z..111827Z violated this for okx — 7 consecutive
runs stopped, recovery only fired on the next cycle's prep, so for ~25
min each cycle the okx target had zero running runs.

Exit 0 = clean, 1 = violation, 2 = data missing.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = ["https://www.okx.com", "http://127.0.0.1:8000"]


def fetch_runs() -> list[dict]:
    env_file = REPO_ROOT / "local-openclaw" / "state" / "scheduler.env"
    token = ""
    base_url = "http://127.0.0.1:18000"
    project_id = "19"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ORCH_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("ORCH_BASE_URL="):
                base_url = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("PROJECT_ID="):
                project_id = line.split("=", 1)[1].strip().strip('"').strip("'")
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
    parser.add_argument(
        "--target", action="append", default=None,
        help=f"fixed target URL (repeatable); defaults to {DEFAULT_TARGETS}",
    )
    args = parser.parse_args(argv)

    targets = args.target or DEFAULT_TARGETS

    try:
        runs = fetch_runs()
    except Exception as exc:
        print(f"[steady-state] cannot fetch runs: {exc}", file=sys.stderr)
        return 2

    by_target: dict[str, dict[str, int]] = {t: {"running": 0, "stopped": 0} for t in targets}
    for r in runs:
        target = r.get("target") or ""
        for t in targets:
            if target.lower() == t.lower() or target.lower().endswith("//" + t.lower().split("//")[-1]):
                bucket = by_target[t]
                status = (r.get("status") or "").lower()
                if status == "running":
                    bucket["running"] += 1
                elif status == "stopped":
                    bucket["stopped"] += 1
                break

    violations = [t for t, c in by_target.items() if c["running"] == 0]

    if not violations:
        for t, c in by_target.items():
            print(f"[steady-state] {t}: running={c['running']} stopped={c['stopped']}",
                  file=sys.stderr)
        return 0

    print(
        f"[steady-state] {len(violations)} fixed target(s) have ZERO running runs at cycle end:",
        file=sys.stderr,
    )
    for t in violations:
        c = by_target[t]
        print(f"  - {t}: running={c['running']} stopped={c['stopped']}", file=sys.stderr)
    print(
        "  ACTION: ui-07 (or another skill) stopped a sole-runner without spawning "
        "a replacement. Pick a redundant run next time, OR follow the STOP click with "
        "POST /projects/<PID>/runs body {\"target\":\"<target>\"} to keep the steady-state "
        "contract. Cycle status will be flagged success_with_dirty_artifacts.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
