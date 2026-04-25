#!/usr/bin/env python3
"""Auto-generate a recall regression report from benchmark history.

The auditor skill's recall investigation checklist tells Hermes to "read
local-hermes-agent/recall-analysis/<latest>.md and diff solved-challenges
set peak-vs-now." But those files are hand-written and stopped being
produced after 2026-04-13 — which is exactly when the sustained recall
regression started. This helper fills that gap: it reads
benchmark-metrics-history.json (which now persists `solved_challenge_names`
per entry thanks to the benchmark_gate update), diffs current vs peak,
and writes a markdown analysis the auditor can cite.

Behaviour:
  - Fail fast with exit 2 when history has no peak record yet or the
    peak record has no `solved_challenge_names` (old entries predate the
    solved-list persistence).
  - Emit exit 0 and the report path when regression data is usable.
  - Emit exit 1 when current recall >= peak (no regression to report).

Usage:
    python3 recall_regression_report.py \\
        --target <url> \\
        [--out-dir local-hermes-agent/recall-analysis] \\
        [--history-file local-hermes-agent/state/benchmark-metrics-history.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY = REPO_ROOT / "local-hermes-agent" / "state" / "benchmark-metrics-history.json"
DEFAULT_OUT_DIR = REPO_ROOT / "local-hermes-agent" / "recall-analysis"


def _recall(rec: dict | None) -> float:
    if not rec:
        return 0.0
    m = rec.get("metrics") if isinstance(rec, dict) else None
    if not isinstance(m, dict):
        return 0.0
    try:
        return float(m.get("challenge_recall") or "0")
    except (TypeError, ValueError):
        return 0.0


def _names(rec: dict | None) -> list[str]:
    if not rec:
        return []
    m = rec.get("metrics") if isinstance(rec, dict) else None
    if not isinstance(m, dict):
        return []
    v = m.get("solved_challenge_names")
    return list(v) if isinstance(v, list) else []


def _strip_difficulty(name: str) -> str:
    """"[difficulty 2] Foo" → "Foo" for easier comparison/display."""
    s = name.strip()
    if s.startswith("[difficulty "):
        end = s.find("] ")
        if end > 0:
            return s[end + 2 :]
    return s


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True,
                        help="target URL key under history.targets (e.g. http://127.0.0.1:8000)")
    parser.add_argument("--history-file", default=str(DEFAULT_HISTORY))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    hist_path = Path(args.history_file)
    if not hist_path.exists():
        print(f"[recall-report] missing history: {hist_path}", file=sys.stderr)
        return 2

    doc = json.loads(hist_path.read_text(encoding="utf-8"))
    tgt = (doc.get("targets") or {}).get(args.target)
    if not isinstance(tgt, dict):
        print(f"[recall-report] target {args.target!r} not in history", file=sys.stderr)
        return 2

    latest = tgt.get("last_metrics") or {}
    latest_rec = {"metrics": latest, "cycle_id": tgt.get("cycle_id"),
                  "updated_at": tgt.get("updated_at")}
    peak_rec = tgt.get("peak") or {}

    if not latest or not peak_rec:
        print("[recall-report] missing latest_metrics or peak; nothing to diff yet",
              file=sys.stderr)
        return 2

    cur_recall = _recall(latest_rec)
    peak_recall = _recall(peak_rec)
    cur_names = set(_names(latest_rec))
    peak_names = set(_names(peak_rec))

    if not peak_names:
        print(
            "[recall-report] peak record has no solved_challenge_names — "
            "peak predates the solved-list persistence added in benchmark_gate.py. "
            "Diff is not possible until a new peak is set.",
            file=sys.stderr,
        )
        return 2

    if cur_recall >= peak_recall:
        print(
            f"[recall-report] current recall {cur_recall:.3f} >= peak {peak_recall:.3f}; "
            "no regression to report",
            file=sys.stderr,
        )
        return 1

    lost = sorted(peak_names - cur_names, key=_strip_difficulty)
    regained = sorted(cur_names - peak_names, key=_strip_difficulty)
    held = peak_names & cur_names

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cycle_id = latest_rec.get("cycle_id") or "unknown"
    out_path = out_dir / f"{today}-{cycle_id}-regression.md"

    body = [
        f"# Recall Regression Report — {cycle_id}",
        "",
        "_Generated automatically by `recall_regression_report.py` from "
        "`benchmark-metrics-history.json`. No manual interpretation added; "
        "the auditor skill's Phase 2 investigation checklist starts here._",
        "",
        "## Score Summary",
        f"- target: {args.target}",
        f"- current: {latest.get('solved_challenges')}/{latest.get('total_challenges')} "
        f"(recall {cur_recall:.3f}, cycle {latest_rec.get('cycle_id')} "
        f"@ {latest_rec.get('updated_at')})",
        f"- peak: {(peak_rec.get('metrics') or {}).get('solved_challenges')}/"
        f"{(peak_rec.get('metrics') or {}).get('total_challenges')} "
        f"(recall {peak_recall:.3f}, cycle {peak_rec.get('cycle_id')} "
        f"@ {peak_rec.get('updated_at')})",
        f"- delta: {cur_recall - peak_recall:+.3f} "
        f"({int(latest.get('solved_challenges', 0)) - int((peak_rec.get('metrics') or {}).get('solved_challenges') or 0):+d} challenges)",
        "",
        f"## Lost since peak ({len(lost)})",
        "These challenges were solved at peak but are not solved in the current "
        "scored run. Each line is a candidate to investigate: find the owning "
        "skill, grep for the challenge name, check log.md for the dispatch/exploit "
        "evidence, and determine what regressed.",
        "",
    ]
    if lost:
        body.extend(f"- {name}" for name in lost)
    else:
        body.append("_(none — diff would be 0 if we reach here, but check logs)_")
    body.extend([
        "",
        f"## New gains ({len(regained)})",
        "Solved now but not at peak. Treat as positive signal — keep the related "
        "skill/prompt behavior.",
        "",
    ])
    if regained:
        body.extend(f"- {name}" for name in regained)
    else:
        body.append("_(none)_")
    body.extend([
        "",
        f"## Held across both ({len(held)})",
        "Solved in both runs — stable baseline. Not regressed; no action unless "
        "you want to expand breadth.",
        "",
    ])
    if held:
        body.extend(f"- {name}" for name in sorted(held, key=_strip_difficulty))

    out_path.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
