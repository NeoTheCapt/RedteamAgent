#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
LOGS_DIR="$ROOT_DIR/logs"
CYCLES_DIR="$LOGS_DIR/cycles"
LOCK_DIR="$STATE_DIR/run.lock"
OPENCLAW_BIN="${OPENCLAW_BIN:-$(command -v openclaw || true)}"
OPENCLAW_SKILL="${OPENCLAW_SKILL:-scan-optimizer-loop}"
OPENCLAW_TIMEOUT_SECONDS="${OPENCLAW_TIMEOUT_SECONDS:-1800}"
MONITOR_POLL_SECONDS="${MONITOR_POLL_SECONDS:-60}"
REPORT_CHANNEL="${REPORT_CHANNEL:-}"
REPORT_TO="${REPORT_TO:-}"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

mkdir -p "$STATE_DIR" "$LOGS_DIR" "$CYCLES_DIR"

iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

fs_now() {
  date -u +%Y%m%dT%H%M%SZ
}

is_terminal_status() {
  case "${1:-}" in
    completed|complete|failed|failure|stopped|cancelled|canceled|succeeded|success|error|errored|timeout)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cycle_id="$(fs_now)"
cycle_dir="$CYCLES_DIR/$cycle_id"
mkdir -p "$cycle_dir"

controller_log="$cycle_dir/controller.log"
prep_log="$cycle_dir/prep.log"
openclaw_log="$cycle_dir/openclaw.log"
final_context_log="$cycle_dir/final-context.log"
report_path="$cycle_dir/report.md"
metadata_path="$cycle_dir/metadata.json"

log() {
  printf '[%s] %s\n' "$(iso_now)" "$*" | tee -a "$controller_log"
}

extract_fixed_issues() {
  if [[ ! -f "$report_path" ]]; then
    return 0
  fi

  awk '
    {
      lower = tolower($0)
    }
    /^2\. / && lower ~ /confirmed bugs fixed/ {capture=1; next}
    /^2\. / && $0 ~ /修复/ {capture=1; next}
    /^3\. / && lower ~ /verification performed/ {capture=0; next}
    /^3\. / && $0 ~ /已执行的验证/ {capture=0; next}
    capture {print}
  ' "$report_path" | sed '/^$/d'
}

extract_openclaw_summary_raw() {
  if [[ -f "$report_path" ]]; then
    awk '
      /^## OpenClaw Summary \(tail\)/ {in_section=1; next}
      in_section && /^```text$/ {in_code=1; next}
      in_code && /^```$/ {exit}
      in_code {print}
    ' "$report_path"
    return 0
  fi

  if [[ -f "$openclaw_log" ]]; then
    tail -n 120 "$openclaw_log"
  fi
}

extract_benchmark_sections() {
  local context_file="$STATE_DIR/latest-context.md"
  [[ -f "$context_file" ]] || return 0
  python3 - "$context_file" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
sections = []
current = []
inside = False
for line in lines:
    if line.startswith('## ') and 'Benchmark Evaluation' in line:
        if current:
            sections.append('\n'.join(current).rstrip())
        current = [line]
        inside = True
        continue
    if inside and line.startswith('## '):
        if current:
            sections.append('\n'.join(current).rstrip())
        current = []
        inside = False
    if inside:
        current.append(line)
if current:
    sections.append('\n'.join(current).rstrip())
if sections:
    print('\n\n'.join(section for section in sections if section.strip()))
PY
}

extract_local_benchmark_metrics_json() {
  local context_file="$STATE_DIR/latest-context.md"
  [[ -f "$context_file" ]] || return 0
  python3 - "$context_file" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
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
if metrics:
    print(json.dumps(metrics))
PY
}

extract_local_benchmark_metrics() {
  local metrics_json
  metrics_json="$(extract_local_benchmark_metrics_json || true)"
  [[ -n "$metrics_json" ]] || return 0
  python3 - "$metrics_json" <<'PY'
import json
import sys

metrics = json.loads(sys.argv[1])
precision = metrics.get('precision', '?')
recall = metrics.get('recall', '?')
f1 = metrics.get('f1', '?')
scenario_precision = metrics.get('scenario_precision', '?')
scenario_actionable = metrics.get('scenario_automation_actionable_recall', metrics.get('automation_actionable_recall', '?'))
print(
    f"Local benchmark: precision {precision} / recall {recall} / f1 {f1} / "
    f"scenario_precision {scenario_precision} / scenario_actionable_recall {scenario_actionable}"
)
PY
}

evaluate_local_benchmark_gate() {
  local mapping_file="$STATE_DIR/target-benchmarks.json"
  local history_file="$STATE_DIR/benchmark-metrics-history.json"
  local metrics_json
  [[ -f "$mapping_file" ]] || return 0
  metrics_json="$(extract_local_benchmark_metrics_json || true)"
  [[ -n "$metrics_json" ]] || return 0
  python3 - "$mapping_file" "$history_file" "$metrics_json" <<'PY'
from pathlib import Path
from statistics import median
import json
import sys

mapping = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
history_path = Path(sys.argv[2])
metrics = json.loads(sys.argv[3])
entry = ((mapping.get('targets') or {}).get('http://127.0.0.1:8000') or {})
gate = entry.get('healthy_skip_gate') or {}
if not gate:
    raise SystemExit(0)

history = {}
if history_path.exists():
    try:
        history = json.loads(history_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        history = {}

target_state = ((history.get('targets') or {}).get('http://127.0.0.1:8000') or {})
records = list(target_state.get('history') or [])
if not records and target_state.get('last_metrics'):
    records = [{
        'updated_at': target_state.get('updated_at'),
        'cycle_id': target_state.get('cycle_id'),
        'metrics': target_state.get('last_metrics'),
    }]

reasons = []
for field, metric_key in [
    ('min_scenario_precision', 'scenario_precision'),
    ('min_scenario_automation_actionable_recall', 'scenario_automation_actionable_recall'),
]:
    if field not in gate:
        continue
    try:
        current = float(metrics.get(metric_key, '0') or 0)
    except ValueError:
        current = 0.0
    threshold = float(gate[field])
    if current < threshold:
        reasons.append(f"{metric_key}={current:.3f} < {threshold:.3f}")

window = int(gate.get('trend_window', 5) or 5)
min_points = int(gate.get('min_history_points', 3) or 3)
max_regression = gate.get('max_regression') or {}
for metric_key, allowed_drop in max_regression.items():
    values = []
    for record in records[-window:]:
        value = ((record or {}).get('metrics') or {}).get(metric_key)
        if value in (None, ''):
            continue
        try:
            values.append(float(value))
        except ValueError:
            continue
    if metric_key not in metrics:
        continue
    try:
        current = float(metrics.get(metric_key, '0') or 0)
        allowed = float(allowed_drop)
    except ValueError:
        continue
    if len(values) >= min_points:
        baseline = median(values)
        if current < baseline - allowed:
            reasons.append(f"{metric_key} trended down vs rolling median {baseline:.3f} -> {current:.3f} (allowed drop {allowed:.3f}, window={min(len(values), window)})")
    elif values:
        baseline = values[-1]
        if current < baseline - allowed:
            reasons.append(f"{metric_key} regressed {baseline:.3f} -> {current:.3f} (allowed drop {allowed:.3f})")

if reasons:
    print('; '.join(reasons))
    raise SystemExit(1)
PY
}

update_local_benchmark_history() {
  local history_file="$STATE_DIR/benchmark-metrics-history.json"
  local metrics_json
  metrics_json="$(extract_local_benchmark_metrics_json || true)"
  [[ -n "$metrics_json" ]] || return 0
  python3 - "$history_file" "$metrics_json" "$cycle_id" <<'PY'
from pathlib import Path
import json
import sys
from datetime import datetime, timezone

history_path = Path(sys.argv[1])
metrics = json.loads(sys.argv[2])
cycle_id = sys.argv[3]
history = {}
if history_path.exists():
    try:
        history = json.loads(history_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        history = {}
payload = history.setdefault('targets', {})
current = payload.get('http://127.0.0.1:8000') or {}
records = list(current.get('history') or [])
if not records and current.get('last_metrics'):
    records = [{
        'updated_at': current.get('updated_at'),
        'cycle_id': current.get('cycle_id'),
        'metrics': current.get('last_metrics'),
    }]
records.append({
    'updated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'cycle_id': cycle_id,
    'metrics': metrics,
})
records = records[-10:]
payload['http://127.0.0.1:8000'] = {
    'updated_at': records[-1]['updated_at'],
    'cycle_id': cycle_id,
    'last_metrics': metrics,
    'history': records,
}
history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
PY
}

send_cycle_started_summary() {
  if [[ -z "$REPORT_CHANNEL" || -z "$REPORT_TO" || -z "$OPENCLAW_BIN" ]]; then
    log "start delivery skipped (REPORT_CHANNEL / REPORT_TO / OPENCLAW_BIN not fully set)"
    return 0
  fi

  local msg_file="$cycle_dir/start-message.txt"
  cat > "$msg_file" <<EOF
Scan optimizer cycle triggered.

Cycle ID: $cycle_id
Started at: $start_at
Monitor poll: ${MONITOR_POLL_SECONDS}s
Observation window: ${OBSERVATION_SECONDS:-300}s
Targets:
- https://www.okx.com
- http://127.0.0.1:8000

Log directory: $cycle_dir
EOF

  set +e
  "$OPENCLAW_BIN" message send --channel "$REPORT_CHANNEL" --target "$REPORT_TO" --message "$(cat "$msg_file")" >> "$controller_log" 2>&1
  local delivery_status=$?
  set -e

  if [[ $delivery_status -eq 0 ]]; then
    log "start summary delivered to $REPORT_CHANNEL:$REPORT_TO"
  else
    log "start summary delivery failed with exit code $delivery_status"
  fi
}

send_cycle_summary() {
  if [[ -z "$REPORT_CHANNEL" || -z "$REPORT_TO" || -z "$OPENCLAW_BIN" ]]; then
    log "summary delivery skipped (REPORT_CHANNEL / REPORT_TO / OPENCLAW_BIN not fully set)"
    return 0
  fi

  local fixed_issues local_benchmark_metrics benchmark_summary_block
  fixed_issues="$(extract_fixed_issues || true)"
  local_benchmark_metrics="$(extract_local_benchmark_metrics || true)"
  benchmark_summary_block=""
  if [[ -n "$local_benchmark_metrics" ]]; then
    benchmark_summary_block="$local_benchmark_metrics"$'\n'
  fi

  local msg_file="$cycle_dir/summary-message.txt"
  if [[ -n "$fixed_issues" ]]; then
    cat > "$msg_file" <<EOF
Scan optimizer cycle finished.

Status: $cycle_status
Cycle ID: $cycle_id
Attempts: $attempt_count
OKX run: ${okx_run_id:-unknown} (${okx_run_status:-unknown})
Local run: ${local_run_id:-unknown} (${local_run_status:-unknown})
${benchmark_summary_block}New commit: ${new_commit:-none}

Fixed issues:
$fixed_issues

Report: $report_path
EOF
  else
    local raw_summary
    raw_summary="$(extract_openclaw_summary_raw || true)"
    if [[ -z "$raw_summary" ]]; then
      raw_summary='(no fixed-issue section extracted, and no raw OpenClaw summary found)'
    fi
    cat > "$msg_file" <<EOF
Scan optimizer cycle finished.

Status: $cycle_status
Cycle ID: $cycle_id
Attempts: $attempt_count
OKX run: ${okx_run_id:-unknown} (${okx_run_status:-unknown})
Local run: ${local_run_id:-unknown} (${local_run_status:-unknown})
${benchmark_summary_block}New commit: ${new_commit:-none}

Fixed issues: (section extraction failed; including raw OpenClaw summary below)
$raw_summary

Report: $report_path
EOF
  fi

  set +e
  "$OPENCLAW_BIN" message send --channel "$REPORT_CHANNEL" --target "$REPORT_TO" --message "$(cat "$msg_file")" >> "$controller_log" 2>&1
  delivery_status=$?
  set -e

  if [[ $delivery_status -eq 0 ]]; then
    log "summary delivered to $REPORT_CHANNEL:$REPORT_TO"
  else
    log "summary delivery failed with exit code $delivery_status"
  fi
}

cleanup_lock() {
  rm -rf "$LOCK_DIR"
}

write_skip_report() {
  cat > "$report_path" <<EOF
# Scan Optimizer Cycle Report

## Cycle Metadata
- cycle_id: $cycle_id
- started_at: $(iso_now)
- status: skipped_overlap
- reason: another cycle already holds the local-openclaw lock
- lock_dir: $LOCK_DIR
- controller_log: $controller_log
EOF
}

refresh_context() {
  set +e
  CYCLE_LOG_DIR="$cycle_dir" "$ROOT_DIR/scripts/build_context.sh" > "$final_context_log" 2>&1
  final_context_status=$?
  set -e

  if [[ $final_context_status -ne 0 ]]; then
    log "final context refresh failed with exit code $final_context_status"
    return $final_context_status
  fi

  if [[ -f "$STATE_DIR/latest-runs.json" ]]; then
    okx_run_id="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.id // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
    local_run_id="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.id // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
    okx_run_status="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.status // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
    local_run_status="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.status // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
  fi
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "another cycle is already running; skipping"
  write_skip_report
  exit 0
fi
trap cleanup_lock EXIT

echo "$cycle_id" > "$LOCK_DIR/cycle_id"
echo "$$" > "$LOCK_DIR/pid"
echo "$(iso_now)" > "$LOCK_DIR/started_at"

start_at="$(iso_now)"
before_commit="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
after_commit="$before_commit"
new_commit=""
prep_status=0
openclaw_status=0
cycle_status="success"
openclaw_ran="false"
summary_excerpt=""
benchmark_gate_reason=""
okx_run_id=""
local_run_id=""
okx_run_status=""
local_run_status=""
attempt_count=0

log "cycle started in $cycle_dir"
log "repo root: $REPO_ROOT"
log "openclaw binary: ${OPENCLAW_BIN:-missing}"
log "skill: $OPENCLAW_SKILL"
log "monitor poll seconds: $MONITOR_POLL_SECONDS"
send_cycle_started_summary

if [[ -z "$OPENCLAW_BIN" ]]; then
  cycle_status="failed_preflight"
  log "openclaw binary not found in PATH"
else
  set +e
  CYCLE_LOG_DIR="$cycle_dir" "$ROOT_DIR/scripts/run_cycle_prep.sh" 2>&1 | tee "$prep_log"
  prep_status=${PIPESTATUS[0]}
  set -e

  if [[ $prep_status -ne 0 ]]; then
    cycle_status="failed_prep"
    if [[ -f "$STATE_DIR/latest-runs.json" ]]; then
      okx_run_id="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.id // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
      local_run_id="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.id // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
      okx_run_status="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.status // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
      local_run_status="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.status // empty' "$STATE_DIR/latest-runs.json" 2>/dev/null || true)"
    fi
    log "prep failed with exit code $prep_status"
  else
    prompt_file="$STATE_DIR/openclaw-prompt.txt"
    created_runs_json="$STATE_DIR/latest-created-runs.json"

    if [[ -f "$created_runs_json" ]]; then
      okx_run_id="$(jq -r '.okx.id // empty' "$created_runs_json" 2>/dev/null || true)"
      local_run_id="$(jq -r '.local.id // empty' "$created_runs_json" 2>/dev/null || true)"
    fi

    while true; do
      attempt_count=$((attempt_count + 1))
      "$ROOT_DIR/scripts/sync_openclaw_skill.sh" >> "$controller_log" 2>&1
      log "openclaw attempt #$attempt_count starting"
      openclaw_ran="true"
      prompt_text="$(cat "$prompt_file")"
      {
        echo "===== attempt $attempt_count @ $(iso_now) ====="
      } >> "$openclaw_log"

      set +e
      "$OPENCLAW_BIN" agent --session-id "local-openclaw-$cycle_id" --message "$prompt_text" --timeout "$OPENCLAW_TIMEOUT_SECONDS" 2>&1 | tee -a "$openclaw_log"
      openclaw_status=${PIPESTATUS[0]}
      set -e

      if [[ $openclaw_status -ne 0 ]]; then
        cycle_status="failed_openclaw"
        log "openclaw exited with code $openclaw_status on attempt #$attempt_count"
      fi

      if [[ -f "$openclaw_log" ]]; then
        summary_excerpt="$(tail -n 120 "$openclaw_log")"
      fi

      refresh_context || true

      after_commit="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
      if [[ -n "$before_commit" && -n "$after_commit" && "$before_commit" != "$after_commit" ]]; then
        new_commit="$after_commit"
      fi

      if [[ -n "$new_commit" ]]; then
        log "detected new local commit $new_commit; cycle can finish"
        cycle_status="success"
        break
      fi

      if grep -q 'NO_ACTIONABLE_BUG_HEALTHY_RUNS' "$openclaw_log" 2>/dev/null; then
        benchmark_gate_reason="$(evaluate_local_benchmark_gate || true)"
        if [[ -n "$benchmark_gate_reason" ]]; then
          cycle_status="failed_benchmark_gate"
          log "benchmark gate blocked healthy skip: $benchmark_gate_reason"
          break
        fi
        cycle_status="skipped_healthy_runs"
        log "openclaw reported no actionable bug; leaving current runs in place and ending this cycle"
        break
      fi

      if [[ "$cycle_status" != "success" ]]; then
        break
      fi

      cycle_status="failed_no_fix_commit"
      log "openclaw finished without a bug-fix commit and without an explicit healthy-skip marker"
      break
    done
  fi
fi

export CYCLE_STATUS="$cycle_status"
export CYCLE_DIR="$cycle_dir"
export CYCLE_REPORT="$report_path"
export CYCLE_ID="$cycle_id"
export BEFORE_COMMIT="$before_commit"
export AFTER_COMMIT="$after_commit"
export PREP_EXIT_CODE="$prep_status"
export OPENCLAW_EXIT_CODE="$openclaw_status"
export OKX_RUN_ID="$okx_run_id"
export LOCAL_RUN_ID="$local_run_id"
export OKX_RUN_STATUS="$okx_run_status"
export LOCAL_RUN_STATUS="$local_run_status"
"$ROOT_DIR/scripts/update_cycle_state.sh" "$new_commit"

{
  echo '{'
  printf '  "cycle_id": %s,\n' "$(jq -Rn --arg v "$cycle_id" '$v')"
  printf '  "started_at": %s,\n' "$(jq -Rn --arg v "$start_at" '$v')"
  printf '  "finished_at": %s,\n' "$(jq -Rn --arg v "$(iso_now)" '$v')"
  printf '  "status": %s,\n' "$(jq -Rn --arg v "$cycle_status" '$v')"
  printf '  "attempt_count": %s,\n' "$attempt_count"
  printf '  "prep_exit_code": %s,\n' "$prep_status"
  printf '  "openclaw_exit_code": %s,\n' "$openclaw_status"
  printf '  "before_commit": %s,\n' "$(jq -Rn --arg v "$before_commit" '$v')"
  printf '  "after_commit": %s,\n' "$(jq -Rn --arg v "$after_commit" '$v')"
  printf '  "new_commit": %s,\n' "$(jq -Rn --arg v "$new_commit" '$v')"
  printf '  "okx_run_id": %s,\n' "$(jq -Rn --arg v "$okx_run_id" '$v')"
  printf '  "local_run_id": %s,\n' "$(jq -Rn --arg v "$local_run_id" '$v')"
  printf '  "okx_run_status": %s,\n' "$(jq -Rn --arg v "$okx_run_status" '$v')"
  printf '  "local_run_status": %s\n' "$(jq -Rn --arg v "$local_run_status" '$v')"
  echo '}'
} > "$metadata_path"

cat > "$report_path" <<EOF
# Scan Optimizer Cycle Report

## Cycle Metadata
- cycle_id: $cycle_id
- started_at: $start_at
- finished_at: $(iso_now)
- status: $cycle_status
- attempt_count: $attempt_count
- repo_root: $REPO_ROOT
- openclaw_bin: ${OPENCLAW_BIN:-missing}
- openclaw_skill: $OPENCLAW_SKILL
- openclaw_timeout_seconds: $OPENCLAW_TIMEOUT_SECONDS
- monitor_poll_seconds: $MONITOR_POLL_SECONDS

## Fixed Targets
- okx: https://www.okx.com
- local: http://127.0.0.1:8000

## Tracked Run IDs
- okx_run_id: ${okx_run_id:-unknown}
- local_run_id: ${local_run_id:-unknown}

## Final Observed Run Status
- okx_run_status: ${okx_run_status:-unknown}
- local_run_status: ${local_run_status:-unknown}

## Benchmark Gate
- local_benchmark_gate: ${benchmark_gate_reason:-pass}

## Exit Codes
- prep_exit_code: $prep_status
- openclaw_exit_code: $openclaw_status
- openclaw_ran: $openclaw_ran

## Git State
- before_commit: ${before_commit:-unknown}
- after_commit: ${after_commit:-unknown}
- new_commit: ${new_commit:-none}

## Important Files
- state_dir: $STATE_DIR
- latest_created_runs: $STATE_DIR/latest-created-runs.json
- latest_runs: $STATE_DIR/latest-runs.json
- latest_context: $STATE_DIR/latest-context.md
- prompt_file: $STATE_DIR/openclaw-prompt.txt
- optimizer_state: $STATE_DIR/optimizer-state.json

## Logs
- controller_log: $controller_log
- prep_log: $prep_log
- openclaw_log: $openclaw_log
- final_context_log: $final_context_log
- metadata_json: $metadata_path

## OpenClaw Summary (tail)
EOF

benchmark_sections="$(extract_benchmark_sections || true)"
if [[ -n "$benchmark_sections" ]]; then
  {
    echo
    echo '## Benchmark Evaluation Snapshot'
    echo
    printf '%s\n' "$benchmark_sections"
  } >> "$report_path"
fi

if [[ -n "$summary_excerpt" ]]; then
  {
    echo '```text'
    printf '%s\n' "$summary_excerpt"
    echo '```'
  } >> "$report_path"
else
  echo '_no openclaw output captured_' >> "$report_path"
fi

if [[ -n "$new_commit" ]]; then
  {
    echo
    echo '## Commit Summary'
    echo '```text'
    git -C "$REPO_ROOT" show --stat --oneline --no-patch "$new_commit" || true
    echo
    git -C "$REPO_ROOT" show --stat --format='' "$new_commit" || true
    echo '```'
    echo
    echo '## Changed Files'
    echo '```text'
    git -C "$REPO_ROOT" diff-tree --no-commit-id --name-only -r "$new_commit" || true
    echo '```'
  } >> "$report_path"
fi

update_local_benchmark_history || true
send_cycle_summary
log "cycle finished with status=$cycle_status report=$report_path"

if [[ "$cycle_status" != "success" ]]; then
  exit 1
fi
