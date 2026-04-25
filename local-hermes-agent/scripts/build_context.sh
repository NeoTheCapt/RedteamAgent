#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
mkdir -p "$STATE_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
TARGET_OKX="${TARGET_OKX:-https://www.okx.com}"
TARGET_LOCAL="${TARGET_LOCAL:-http://127.0.0.1:8000}"
SKIP_LOCAL_SCORE="${HERMES_SKIP_JUICE_SHOP_SCORE:-0}"

LATEST_RUNS_JSON="$STATE_DIR/latest-runs.json"
OUT_FILE="$STATE_DIR/latest-context.md"
HISTORY_FILE="$STATE_DIR/benchmark-metrics-history.json"

orchestrator_curl "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$LATEST_RUNS_JSON"

python3 - <<'PY' "$LATEST_RUNS_JSON" "$OUT_FILE" "$HISTORY_FILE" "$TARGET_OKX" "$TARGET_LOCAL" "$SKIP_LOCAL_SCORE"
import json
import os
import sqlite3
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

latest_runs_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
history_path = Path(sys.argv[3])
target_okx = sys.argv[4].rstrip('/')
target_local = sys.argv[5].rstrip('/')
skip_local_score = sys.argv[6] == '1'

runs = json.loads(latest_runs_path.read_text(encoding='utf-8')) if latest_runs_path.exists() else []

def target_matches(run_target: str, target: str) -> bool:
    return (run_target or '').rstrip('/') == target.rstrip('/')

def latest_for(target: str):
    matches = [r for r in runs if target_matches(r.get('target', ''), target)]
    if not matches:
        return None
    def key(r):
        return (str(r.get('created_at') or ''), int(r.get('id') or 0))
    return sorted(matches, key=key)[-1]

def active_count(target: str) -> int:
    return sum(1 for r in runs if target_matches(r.get('target', ''), target) and r.get('status') in {'queued', 'running'})

def load_run_json(run):
    if not run:
        return {}
    p = Path(run.get('engagement_root', '')) / 'run.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}

def find_engagement_dir(run_json):
    root = run_json.get('workspace_root') or ''
    if not root:
        return None
    eng_root = Path(root) / 'engagements'
    if not eng_root.exists():
        return None
    candidates = [p for p in eng_root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return sorted(candidates)[-1]

def findings_count(findings_md: Path) -> int:
    if not findings_md.exists():
        return 0
    count = 0
    for line in findings_md.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('## [FINDING-'):
            count += 1
    return count

def coverage_for(db_path: Path):
    if not db_path.exists() or not db_path.is_file():
        return {
            'total_cases': 0,
            'completed_cases': 0,
            'pending_cases': 0,
            'processing_cases': 0,
            'error_cases': 0,
            'case_types': [],
            'source_counts': [],
        }
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        status_counts = Counter()
        for status, count in cur.execute('select status, count(*) from cases group by status'):
            status_counts[status] = count
        type_counts = []
        for row in cur.execute("select type, count(*) as total, sum(case when status='done' then 1 else 0 end) as done, sum(case when status='pending' then 1 else 0 end) as pending, sum(case when status='processing' then 1 else 0 end) as processing, sum(case when status='error' then 1 else 0 end) as error from cases group by type order by total desc"):
            type_counts.append({'type': row[0], 'total': row[1], 'done': row[2] or 0, 'pending': row[3] or 0, 'processing': row[4] or 0, 'error': row[5] or 0})
        source_counts = [{'source': source, 'count': count} for source, count in cur.execute('select source, count(*) from cases group by source order by count(*) desc')]
        total_cases = sum(status_counts.values())
        return {
            'total_cases': total_cases,
            'completed_cases': status_counts.get('done', 0),
            'pending_cases': status_counts.get('pending', 0),
            'processing_cases': status_counts.get('processing', 0),
            'error_cases': status_counts.get('error', 0),
            'case_types': type_counts,
            'source_counts': source_counts,
        }
    finally:
        con.close()

def surfaces_for(path: Path):
    if not path.exists() or not path.is_file():
        return {'total_surfaces': 0, 'surface_types': [], 'surface_statuses': {}}
    status_counts = Counter()
    type_counts = Counter()
    total = 0
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            row = json.loads(line)
        except Exception:
            continue
        status_counts[row.get('status') or 'unknown'] += 1
        type_counts[row.get('surface_type') or 'unknown'] += 1
    return {
        'total_surfaces': total,
        'surface_types': [{'type': k, 'count': v} for k, v in type_counts.most_common()],
        'surface_statuses': dict(status_counts),
    }

def crawler_stats(eng_dir: Path):
    scans = eng_dir / 'scans'
    katana_output = scans / 'katana_output.jsonl'
    katana_error = scans / 'katana_error.log'
    lines = 0
    if katana_output.exists():
        with katana_output.open('r', encoding='utf-8', errors='replace') as fh:
            for _ in fh:
                lines += 1
    err_tail = ''
    if katana_error.exists():
        err_lines = katana_error.read_text(encoding='utf-8', errors='replace').splitlines()
        err_tail = '\n'.join(err_lines[-5:])
    return {
        'katana_output_lines': lines,
        'katana_error_tail': err_tail,
    }

def build_summary(run):
    if not run:
        return None
    run_json = load_run_json(run)
    eng_dir = find_engagement_dir(run_json)
    coverage = coverage_for(eng_dir / 'cases.db') if eng_dir else coverage_for(Path())
    surfaces = surfaces_for(eng_dir / 'surfaces.jsonl') if eng_dir else surfaces_for(Path())
    crawler = crawler_stats(eng_dir) if eng_dir else {'katana_output_lines': 0, 'katana_error_tail': ''}
    findings = findings_count(eng_dir / 'findings.md') if eng_dir else 0
    return {
        'target': {
            'target': run.get('target'),
            'engagement_dir': str(eng_dir) if eng_dir else '',
            'status': (run_json.get('status') or ('in_progress' if run.get('status') in {'queued', 'running'} else 'completed')),
        },
        'overview': {
            'findings_count': findings,
            'current_phase': run_json.get('current_phase') or run_json.get('phase') or '',
            'updated_at': run.get('updated_at'),
            'run_status': run.get('status'),
        },
        'coverage': {
            **coverage,
            **surfaces,
        },
        'crawler': crawler,
        'integrity': {
            'coverage_source': 'artifact-summary',
            'observed_paths_source': 'artifact-summary',
            'reasons': [],
        },
    }

def json_block(value):
    return json.dumps(value, indent=2, ensure_ascii=False)

okx_run = latest_for(target_okx)
local_run = latest_for(target_local)
fixed_target_state = {
    'okx': {
        'target': target_okx,
        'total_runs': sum(1 for r in runs if target_matches(r.get('target', ''), target_okx)),
        'active_runs': active_count(target_okx),
        'latest_run': okx_run,
    },
    'local': {
        'target': target_local,
        'total_runs': sum(1 for r in runs if target_matches(r.get('target', ''), target_local)),
        'active_runs': active_count(target_local),
        'latest_run': local_run,
    },
    'unexpected_active_runs': [
        r for r in runs
        if r.get('status') in {'queued', 'running'}
        and not target_matches(r.get('target', ''), target_okx)
        and not target_matches(r.get('target', ''), target_local)
    ],
}

okx_summary = build_summary(okx_run)
local_summary = build_summary(local_run)

challenge_lines = []
challenge_data = None
local_status = (local_run or {}).get('status') or ''
if skip_local_score:
    challenge_lines.extend([
        '- status: deferred',
        f'- local_run_status: {local_status or "unknown"}',
        '- reason: local run already scored in a prior cycle; score refresh skipped by controller',
    ])
elif local_status.rstrip() == 'completed':
    try:
        api_url = target_local.rstrip('/') + '/api/Challenges'
        with urllib.request.urlopen(api_url, timeout=20) as resp:
            payload = json.load(resp)
        items = payload.get('data', payload)
        solved = [item for item in items if item.get('solved')]
        unsolved = [item for item in items if not item.get('solved')]
        by_category = defaultdict(lambda: {'solved': 0, 'total': 0})
        for item in items:
            category = item.get('category') or 'Unknown'
            by_category[category]['total'] += 1
            if item.get('solved'):
                by_category[category]['solved'] += 1
        challenge_data = {
            'status': 'scored',
            'local_run_status': local_status,
            'source': 'Juice Shop /api/Challenges (ground truth)',
            'total_challenges': len(items),
            'solved_challenges': len(solved),
            'unsolved_challenges': len(unsolved),
            'challenge_recall': f"{(len(solved) / len(items)) if items else 0:.3f}",
            'category_breakdown': {
                category: f"{data['solved']}/{data['total']}"
                for category, data in sorted(by_category.items())
            },
            'solved_challenge_names': [f"[difficulty {item.get('difficulty')}] {item.get('name')}" for item in solved],
            'unsolved_challenge_names': [f"[difficulty {item.get('difficulty')}] {item.get('name')}" for item in unsolved],
        }
        challenge_lines.extend([
            '- status: scored',
            f'- local_run_status: {local_status}',
            '- source: Juice Shop /api/Challenges (ground truth)',
            f'- total_challenges: {challenge_data["total_challenges"]}',
            f'- solved_challenges: {challenge_data["solved_challenges"]}',
            f'- unsolved_challenges: {challenge_data["unsolved_challenges"]}',
            f'- challenge_recall: {challenge_data["challenge_recall"]}',
            '',
            '### Category Breakdown',
        ])
        for category, score in challenge_data['category_breakdown'].items():
            challenge_lines.append(f'- {category}: {score}')
        challenge_lines.extend(['', '### Solved Challenges'])
        for row in challenge_data['solved_challenge_names']:
            challenge_lines.append(f'- {row}')
        challenge_lines.extend(['', '### Unsolved Challenges'])
        for row in challenge_data['unsolved_challenge_names']:
            challenge_lines.append(f'- {row}')
    except Exception as exc:
        challenge_lines.extend([
            '- status: api_error',
            f'- local_run_status: {local_status}',
            f'- reason: {exc}',
        ])
else:
    challenge_lines.extend([
        '- status: deferred',
        f'- local_run_status: {local_status or "unknown"}',
        '- reason: local run has not completed; challenge score requires completed status',
    ])

history_lines = []
if history_path.exists():
    try:
        history = json.loads(history_path.read_text(encoding='utf-8'))
    except Exception:
        history = {}
else:
    history = {}
records = list((((history.get('targets') or {}).get(target_local) or {}).get('history') or []))
if records:
    for record in records[-5:]:
        metrics = (record or {}).get('metrics') or {}
        history_lines.append(
            f"- cycle {(record or {}).get('cycle_id', '?')}: recall={metrics.get('challenge_recall', '?')}, solved={metrics.get('solved_challenges', '?')}/{metrics.get('total_challenges', '?')}"
        )
else:
    history_lines.append('- No challenge score history available yet.')

parts = [
    '# Latest Scan Optimizer Context',
    '',
    '## Fixed Target State',
    '',
    json_block(fixed_target_state),
    '',
    '## Runs (latest per target)',
    '',
    json_block([r for r in [okx_run, local_run] if r]),
    '',
    '## OKX Summary',
    '',
    json_block(okx_summary or {'target': target_okx, 'status': 'missing'}),
    '',
    '## Local Summary',
    '',
    json_block(local_summary or {'target': target_local, 'status': 'missing'}),
    '',
    '## Local Challenge Score',
    '',
    '\n'.join(challenge_lines),
    '',
    '## Challenge Score History',
    '',
    '\n'.join(history_lines),
    '',
]
out_path.write_text('\n'.join(parts), encoding='utf-8')
print(str(out_path))
PY
