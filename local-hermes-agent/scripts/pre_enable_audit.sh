#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
JOB_ID="${SCAN_OPTIMIZER_JOB_ID:-b5d720c53e26}"
EXPECTED_SKILL="${SCAN_OPTIMIZER_SKILL:-scan-optimizer-hermes}"
LEGACY_LABEL="${LEGACY_SCAN_OPTIMIZER_LABEL:-com.neothecapt.redteamopencode.scan-optimizer}"
LEGACY_PLIST_PATH="${LEGACY_SCAN_OPTIMIZER_PLIST:-$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist}"
WITH_TESTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-tests)
      WITH_TESTS=1
      shift
      ;;
    *)
      echo "usage: $0 [--with-tests]" >&2
      exit 2
      ;;
  esac
done

STATE_DIR="$REPO_ROOT/local-hermes-agent/state"
SCRIPTS_DIR="$REPO_ROOT/local-hermes-agent/scripts"
ORCH_DIR="$REPO_ROOT/orchestrator"
CRON_STORE="$HERMES_HOME_DIR/cron/jobs.json"

failures=0
passes=0
skips=0

report() {
  local name="$1"
  local status="$2"
  local detail="$3"
  printf '%s: %s - %s\n' "$name" "$status" "$detail"
  case "$status" in
    PASS) passes=$((passes + 1)) ;;
    FAIL) failures=$((failures + 1)) ;;
    SKIP) skips=$((skips + 1)) ;;
  esac
}

require_file() {
  local label="$1"
  local path="$2"
  if [[ -f "$path" ]]; then
    report "$label" PASS "$path"
  else
    report "$label" FAIL "missing: $path"
  fi
}

require_executable_or_file() {
  local label="$1"
  local path="$2"
  if [[ -x "$path" || -f "$path" ]]; then
    report "$label" PASS "$path"
  else
    report "$label" FAIL "missing: $path"
  fi
}

cron_field() {
  local field="$1"
  python3 - "$CRON_STORE" "$JOB_ID" "$field" <<'PY'
import json, sys
from pathlib import Path

store = Path(sys.argv[1])
job_id = sys.argv[2]
field = sys.argv[3]
if not store.exists():
    print("")
    sys.exit(0)
try:
    data = json.loads(store.read_text(encoding='utf-8'))
except Exception:
    print("")
    sys.exit(0)
for job in data.get('jobs', []):
    if job.get('id') == job_id:
        value = job.get(field)
        if isinstance(value, list):
            print(','.join(str(v) for v in value))
        elif value is None:
            print("")
        else:
            print(str(value))
        break
else:
    print("")
PY
}

report "repo root" PASS "$REPO_ROOT"
require_file "scheduler env" "$STATE_DIR/scheduler.env"
require_executable_or_file "run_cycle_prep.sh" "$SCRIPTS_DIR/run_cycle_prep.sh"
require_executable_or_file "build_context.sh" "$SCRIPTS_DIR/build_context.sh"
require_executable_or_file "update_cycle_state.sh" "$SCRIPTS_DIR/update_cycle_state.sh"
require_executable_or_file "orchestrator run.sh" "$ORCH_DIR/run.sh"
require_executable_or_file "orchestrator stop.sh" "$ORCH_DIR/stop.sh"

legacy_loaded=0
if command -v launchctl >/dev/null 2>&1; then
  if launchctl list 2>/dev/null | grep -q "$LEGACY_LABEL"; then
    legacy_loaded=1
  fi
fi
if [[ ! -f "$LEGACY_PLIST_PATH" && "$legacy_loaded" -eq 0 ]]; then
  report "legacy scheduler" PASS "launchd label not installed or loaded"
else
  detail=""
  if [[ -f "$LEGACY_PLIST_PATH" ]]; then
    detail="plist present at $LEGACY_PLIST_PATH"
  else
    detail="launchctl still lists $LEGACY_LABEL"
  fi
  report "legacy scheduler" FAIL "$detail"
fi

if [[ -f "$CRON_STORE" ]]; then
  report "hermes cron store" PASS "$CRON_STORE"
else
  report "hermes cron store" FAIL "missing: $CRON_STORE"
fi

cron_name="$(cron_field name)"
cron_skill="$(cron_field skill)"
cron_enabled="$(cron_field enabled)"
cron_state="$(cron_field state)"

if [[ -z "$cron_name" ]]; then
  report "hermes cron job" FAIL "job id $JOB_ID not found in $CRON_STORE"
else
  report "hermes cron job" PASS "$cron_name ($JOB_ID)"
fi

if [[ "$cron_skill" == "$EXPECTED_SKILL" ]]; then
  report "hermes cron skill" PASS "$cron_skill"
else
  report "hermes cron skill" FAIL "expected $EXPECTED_SKILL, got ${cron_skill:-missing}"
fi

if [[ "$cron_enabled" == "False" || "$cron_enabled" == "false" ]] && [[ "$cron_state" == "paused" ]]; then
  report "hermes cron paused" PASS "enabled=$cron_enabled state=$cron_state"
else
  report "hermes cron paused" FAIL "expected enabled=false and state=paused, got enabled=${cron_enabled:-missing} state=${cron_state:-missing}"
fi

if [[ "$WITH_TESTS" -eq 1 ]]; then
  if bash "$REPO_ROOT/tests/agent-contracts/test_update_cycle_state_records_invocation_id.sh" >/dev/null 2>&1; then
    report "state regression test" PASS "test_update_cycle_state_records_invocation_id.sh"
  else
    report "state regression test" FAIL "test_update_cycle_state_records_invocation_id.sh"
  fi

  if bash "$REPO_ROOT/tests/agent-contracts/test_run_cycle_hermes_rejects_stale_state.sh" >/dev/null 2>&1; then
    report "stale-state regression test" PASS "test_run_cycle_hermes_rejects_stale_state.sh"
  else
    report "stale-state regression test" FAIL "test_run_cycle_hermes_rejects_stale_state.sh"
  fi
else
  report "regression tests" SKIP "rerun with --with-tests to execute shell regression checks"
fi

printf 'summary: passes=%s fails=%s skips=%s\n' "$passes" "$failures" "$skips"
if [[ "$failures" -eq 0 ]]; then
  echo 'overall: PASS'
  exit 0
fi

echo 'overall: FAIL'
exit 1
