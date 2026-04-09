#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
PROMPTS_DIR="$ROOT_DIR/prompts"
LOGS_DIR="${CYCLE_LOG_DIR:-$ROOT_DIR/logs}"
REFRESH_ORCHESTRATOR="${REFRESH_ORCHESTRATOR:-1}"

mkdir -p "$STATE_DIR" "$LOGS_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
ORCH_TOKEN="${ORCH_TOKEN:-}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
TARGET_OKX="${TARGET_OKX:-https://www.okx.com}"
TARGET_LOCAL="${TARGET_LOCAL:-http://127.0.0.1:8000}"

LATEST_RUNS_JSON="$STATE_DIR/latest-runs.json"


timestamp() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

refresh_runs_json() {
    orchestrator_curl \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$LATEST_RUNS_JSON"
}

latest_run_id_for_target() {
    local target="$1"
    jq -r --arg target "$target" '
        [ .[] | select(.target == $target) ] | last.id // empty
    ' "$LATEST_RUNS_JSON"
}

active_run_count_for_target() {
    local target="$1"
    jq -r --arg target "$target" '
        [ .[] | select(.target == $target and (.status == "queued" or .status == "running")) ] | length
    ' "$LATEST_RUNS_JSON"
}

unexpected_active_runs_json() {
    jq -c --arg okx "$TARGET_OKX" --arg local "$TARGET_LOCAL" '
        [ .[] | select((.status == "queued" or .status == "running") and (.target != $okx and .target != $local)) ]
    ' "$LATEST_RUNS_JSON"
}

verify_live_projection() {
    local run_id="$1"
    local label="$2"
    [[ -n "$run_id" ]] || return 0

    local snapshot_json
    snapshot_json="$(python3 "$ROOT_DIR/scripts/run_context_snapshot.py" "$run_id")"

    local projection_mismatch artifact_reasons
    projection_mismatch="$(printf '%s\n' "$snapshot_json" | jq -r '((.artifact.integrity.summary_api_suspicious // false) or (.artifact.integrity.observed_api_suspicious // false))')"
    artifact_reasons="$(printf '%s\n' "$snapshot_json" | jq -r '(.artifact.integrity.reasons // []) | map(select(startswith("artifact_"))) | join(", ")')"

    if [[ "$projection_mismatch" == "true" ]]; then
        echo "[$(timestamp)] live projection mismatch for $label run $run_id" >&2
        printf '%s\n' "$snapshot_json" | jq '{run_id: .summary.target.target, integrity: .artifact.integrity, api_coverage: .summary.coverage, artifact_cases: .artifact.cases}' >&2
        return 1
    fi

    if [[ -n "$artifact_reasons" ]]; then
        echo "[$(timestamp)] non-fatal artifact anomaly for $label run $run_id: $artifact_reasons" >&2
    fi

    return 0
}

verify_fixed_target_runs() {
    local needs_rebuild=0
    refresh_runs_json

    local okx_id local_id okx_active_count local_active_count unexpected_active_json unexpected_active_count
    okx_id="$(latest_run_id_for_target "$TARGET_OKX")"
    local_id="$(latest_run_id_for_target "$TARGET_LOCAL")"
    okx_active_count="$(active_run_count_for_target "$TARGET_OKX")"
    local_active_count="$(active_run_count_for_target "$TARGET_LOCAL")"
    unexpected_active_json="$(unexpected_active_runs_json)"
    unexpected_active_count="$(printf '%s\n' "$unexpected_active_json" | jq 'length')"

    if [[ -z "$okx_id" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: no latest run exists for $TARGET_OKX" >&2
    fi
    if [[ -z "$local_id" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: no latest run exists for $TARGET_LOCAL" >&2
    fi
    if [[ "$okx_active_count" != "1" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: expected exactly 1 active run for $TARGET_OKX but found $okx_active_count" >&2
    fi
    if [[ "$local_active_count" != "1" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: expected exactly 1 active run for $TARGET_LOCAL but found $local_active_count" >&2
    fi
    if [[ "$unexpected_active_count" != "0" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: unexpected active non-fixed-target runs detected:" >&2
        printf '%s\n' "$unexpected_active_json" | jq '.' >&2
    fi

    verify_live_projection "$okx_id" "okx" || needs_rebuild=1
    verify_live_projection "$local_id" "local" || needs_rebuild=1

    return "$needs_rebuild"
}

if [[ "$REFRESH_ORCHESTRATOR" == "1" ]]; then
    echo "[$(timestamp)] restarting local orchestrator to refresh live run state before snapshot..."
    (
        cd "$REPO_DIR"
        ./orchestrator/stop.sh >/dev/null 2>&1 || true
        ./orchestrator/run.sh
    ) | tee "$LOGS_DIR/orchestrator-refresh.log"

    if ! verify_fixed_target_runs; then
        echo "[$(timestamp)] plain restart left summary/observed-path drift; rebuilding orchestrator..." | tee -a "$LOGS_DIR/orchestrator-refresh.log"
        (
            cd "$REPO_DIR"
            ./orchestrator/stop.sh >/dev/null 2>&1 || true
            ./orchestrator/run.sh --rebuild
        ) | tee -a "$LOGS_DIR/orchestrator-refresh.log"

        verify_fixed_target_runs
    fi
fi

append_benchmark_gate_snapshot() {
    local prompt_file="$1"
    local context_file="$STATE_DIR/latest-context.md"
    local mapping_file="$STATE_DIR/target-benchmarks.json"
    local history_file="$STATE_DIR/benchmark-metrics-history.json"
    [[ -f "$context_file" && -f "$mapping_file" ]] || return 0

    python3 - "$context_file" "$mapping_file" "$history_file" >> "$prompt_file" <<'PY'
from pathlib import Path
import json
import sys

context_path = Path(sys.argv[1])
mapping_path = Path(sys.argv[2])
history_path = Path(sys.argv[3])
lines = context_path.read_text(encoding='utf-8', errors='replace').splitlines()
inside = False
metrics = {}
for line in lines:
    if line.startswith('## Local Benchmark Evaluation'):
        inside = True
        continue
    if inside and (line.startswith('## ') or line.startswith('#### ')):
        break
    if inside and line.startswith('- '):
        key, _, value = line[2:].partition(':')
        if key and value:
            metrics[key.strip()] = value.strip()
if not metrics:
    raise SystemExit(0)

mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
entry = ((mapping.get('targets') or {}).get('http://127.0.0.1:8000') or {})
gate = entry.get('healthy_skip_gate') or {}
history = {}
if history_path.exists():
    try:
        history = json.loads(history_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        history = {}
previous = (((history.get('targets') or {}).get('http://127.0.0.1:8000') or {}).get('last_metrics') or {})

reasons = []
for field, metric_key in [
    ('min_scenario_precision', 'scenario_precision'),
    ('min_scenario_automation_actionable_recall', 'scenario_automation_actionable_recall'),
]:
    if field not in gate:
        continue
    current = float(metrics.get(metric_key, '0') or 0)
    threshold = float(gate[field])
    if current < threshold:
        reasons.append(f"{metric_key}={current:.3f} < {threshold:.3f}")
for metric_key, allowed_drop in (gate.get('max_regression') or {}).items():
    if metric_key not in metrics or metric_key not in previous:
        continue
    current = float(metrics.get(metric_key, '0') or 0)
    last = float(previous.get(metric_key, '0') or 0)
    allowed = float(allowed_drop)
    if current < last - allowed:
        reasons.append(f"{metric_key} regressed {last:.3f} -> {current:.3f} (allowed drop {allowed:.3f})")

print('\n## Runtime Benchmark Gate Snapshot\n')
print('- Target: http://127.0.0.1:8000')
for key in ('precision', 'recall', 'f1', 'scenario_precision', 'scenario_recall', 'scenario_f1', 'scenario_automation_actionable_recall'):
    if key in metrics:
        print(f'- {key}: {metrics[key]}')
if gate:
    print(f"- Gate thresholds: min_scenario_precision={gate.get('min_scenario_precision', 'n/a')}, min_scenario_automation_actionable_recall={gate.get('min_scenario_automation_actionable_recall', 'n/a')}")
if reasons:
    print('- Gate result: FAIL')
    print(f"- Gate reason: {'; '.join(reasons)}")
    print('- Instruction: Do not conclude NO_ACTIONABLE_BUG_HEALTHY_RUNS while this benchmark gate is failing. Treat low or regressed benchmark quality as actionable optimizer work and improve general detection / correlation / execution / reporting logic without target-specific hardcoding.')
else:
    print('- Gate result: PASS')
PY
}

echo "[$(timestamp)] building latest run context before taking action..."
"$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"

cp "$PROMPTS_DIR/scan-optimizer-loop.txt" "$STATE_DIR/openclaw-prompt.txt"
append_benchmark_gate_snapshot "$STATE_DIR/openclaw-prompt.txt"

echo "[$(timestamp)] prepared OpenClaw cycle inputs:"
echo "- context: $STATE_DIR/latest-context.md"
echo "- prompt:  $STATE_DIR/openclaw-prompt.txt"
