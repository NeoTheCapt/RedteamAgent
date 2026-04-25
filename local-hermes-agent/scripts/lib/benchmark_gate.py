#!/usr/bin/env python3
"""Challenge score history tracker for local-hermes-agent.

Parses challenge metrics from latest-context.md and appends them to
the benchmark history file for trend tracking across cycles.

Usage:
    python3 scripts/lib/benchmark_gate.py \
        --context-file FILE --history-file FILE \
        --mode update-history --cycle-id ID
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


TARGET_DEFAULT = "http://127.0.0.1:8000"


def parse_metrics_from_context(context_path: Path) -> dict:
    """Parse '## Local Challenge Score' section into key-value dict.

    Also captures the per-challenge name lists from the nested
    '### Solved Challenges' / '### Unsolved Challenges' sub-sections so
    history can answer "which challenges regressed from peak to now"
    without the auditor re-scraping latest-context.md every time. Without
    this, solved sets get overwritten every cycle (verified on cycle
    20260424T160049Z, which obliterated the 15/111 peak's solved list
    before any recall-analysis report could be written).
    """
    lines = context_path.read_text(encoding='utf-8', errors='replace').splitlines()
    section = None  # None | 'kv' | 'solved' | 'unsolved'
    metrics: dict = {}
    solved: list[str] = []
    unsolved: list[str] = []

    for line in lines:
        if line.startswith('## Local Challenge Score'):
            section = 'kv'
            continue
        if section is not None and line.startswith('## '):
            # next top-level section ends our scope
            break
        if section is not None and line.startswith('### '):
            heading = line[4:].strip().lower()
            if heading == 'solved challenges':
                section = 'solved'
            elif heading == 'unsolved challenges':
                section = 'unsolved'
            else:
                section = 'kv'  # unknown sub-section; keep in kv mode (ignore rows)
            continue
        if section == 'kv' and line.startswith('- '):
            key, _, value = line[2:].partition(':')
            if key and value:
                metrics[key.strip()] = value.strip()
        elif section == 'solved' and line.startswith('- '):
            solved.append(line[2:].strip())
        elif section == 'unsolved' and line.startswith('- '):
            unsolved.append(line[2:].strip())

    if solved:
        metrics['solved_challenge_names'] = solved
    if unsolved:
        metrics['unsolved_challenge_names'] = unsolved
    return metrics


def load_history(history_path: Path) -> dict:
    """Load history JSON, returning empty dict on missing or invalid file."""
    if not history_path.exists():
        return {}
    try:
        return json.loads(history_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def mode_update_history(context_path: Path, history_path: Path, target: str,
                        cycle_id: str) -> int:
    """Append current metrics to history file. Exit 0 always."""
    if not context_path.exists():
        return 0
    metrics = parse_metrics_from_context(context_path)
    if not metrics:
        return 0
    # Skip entries without a valid challenge_recall.
    recall_raw = metrics.get('challenge_recall', '')
    if not recall_raw or recall_raw in ('api_error', 'JUDGE_ERROR'):
        return 0

    max_records = int(os.environ.get('HERMES_BENCHMARK_HISTORY_SIZE', '10') or 10)
    history = load_history(history_path)

    payload = history.setdefault('targets', {})
    current = payload.get(target) or {}
    records = list(current.get('history') or [])
    if not records and current.get('last_metrics'):
        records = [{
            'updated_at': current.get('updated_at'),
            'cycle_id': current.get('cycle_id'),
            'metrics': current.get('last_metrics'),
        }]

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    records.append({
        'updated_at': now_str,
        'cycle_id': cycle_id,
        'metrics': metrics,
    })
    records = records[-max_records:]

    # Peak is maintained monotonically — once a recall value lands as the
    # highest observed, we stick it in `peak` forever (until a higher one
    # comes along). History is trimmed to the last N entries for size, so
    # computing peak from the trimmed tail alone would silently drop the
    # true peak as older entries rotate out. Prior behavior had NO peak
    # field at all, which caused the auditor to invent peak values from
    # scraped text across 8 different cycles (0.036 / 0.063 / 0.117 / 0.162
    # reported for the SAME target).
    def _recall_float(rec_or_metrics) -> float:
        if rec_or_metrics is None:
            return 0.0
        m = rec_or_metrics if isinstance(rec_or_metrics, dict) and 'challenge_recall' in rec_or_metrics \
            else (rec_or_metrics.get('metrics') or {} if isinstance(rec_or_metrics, dict) else {})
        try:
            return float(m.get('challenge_recall') or '0')
        except (TypeError, ValueError):
            return 0.0

    # Current record is the last one just appended.
    current_record = records[-1]
    current_recall = _recall_float(current_record)

    # Preserve existing peak if present; only overwrite when current beats it.
    existing_peak = current.get('peak')
    existing_peak_recall = _recall_float(existing_peak) if existing_peak else 0.0
    if current_recall > existing_peak_recall:
        peak_block = {
            'cycle_id': current_record.get('cycle_id'),
            'updated_at': current_record.get('updated_at'),
            'metrics': current_record.get('metrics'),
        }
    else:
        peak_block = existing_peak

    payload[target] = {
        'updated_at': records[-1]['updated_at'],
        'cycle_id': cycle_id,
        'last_metrics': metrics,
        'history': records,
    }
    if peak_block is not None:
        payload[target]['peak'] = peak_block

    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Challenge score history tracker for local-hermes-agent.'
    )
    parser.add_argument('--context-file', required=True, help='Path to latest-context.md')
    parser.add_argument('--history-file', required=True, help='Path to benchmark-metrics-history.json')
    parser.add_argument('--mode', required=True, choices=['update-history'], help='Operation mode')
    parser.add_argument('--cycle-id', default='', help='Cycle ID for this history entry')
    args = parser.parse_args()

    target = os.environ.get('TARGET_LOCAL', TARGET_DEFAULT)

    exit_code = mode_update_history(
        context_path=Path(args.context_file),
        history_path=Path(args.history_file),
        target=target,
        cycle_id=args.cycle_id,
    )
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
