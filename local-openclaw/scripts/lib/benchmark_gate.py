#!/usr/bin/env python3
"""Challenge score history tracker for local-openclaw.

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
    """Parse '## Local Challenge Score' section into key-value dict."""
    lines = context_path.read_text(encoding='utf-8', errors='replace').splitlines()
    inside = False
    metrics = {}
    for line in lines:
        if line.startswith('## Local Challenge Score'):
            inside = True
            continue
        if inside and line.startswith('## '):
            break
        if inside and line.startswith('### '):
            break
        if inside and line.startswith('- '):
            key, _, value = line[2:].partition(':')
            if key and value:
                metrics[key.strip()] = value.strip()
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

    max_records = int(os.environ.get('OPENCLAW_BENCHMARK_HISTORY_SIZE', '10') or 10)
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

    payload[target] = {
        'updated_at': records[-1]['updated_at'],
        'cycle_id': cycle_id,
        'last_metrics': metrics,
        'history': records,
    }

    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Challenge score history tracker for local-openclaw.'
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
