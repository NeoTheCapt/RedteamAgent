#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
ENV_FILE="${LOCAL_OPENCLAW_ENV_FILE:-$STATE_DIR/scheduler.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "scheduler env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

invocation_id="${HERMES_RUN_INVOCATION_ID:-hermes-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
export HERMES_RUN_INVOCATION_ID="$invocation_id"

export REPORT_CHANNEL=""
export REPORT_TO=""
export SYNC_OPENCLAW_SKILL=0
export HERMES_SKILL="${HERMES_SKILL:-scan-optimizer-hermes}"
export OPENCLAW_SKILL="$HERMES_SKILL"
export OPENCLAW_BIN="$ROOT_DIR/scripts/hermes_openclaw_compat.sh"
export HERMES_TOOLSETS="${HERMES_TOOLSETS:-terminal,file,skills}"
export HERMES_SOURCE_TAG="${HERMES_SOURCE_TAG:-redteam-scan-optimizer}"

set +e
"$ROOT_DIR/scripts/run_cycle.sh"
cycle_exit=$?
set -e

state_file="$STATE_DIR/optimizer-state.json"
if [[ ! -f "$state_file" ]]; then
  echo "# Hermes Scan Optimizer Cycle"
  echo
  echo "- status: missing_optimizer_state"
  echo "- invocation_id: $invocation_id"
  echo "- exit_code: $cycle_exit"
  if (( cycle_exit == 0 )); then
    exit 1
  fi
  exit "$cycle_exit"
fi

state_invocation_id="$(jq -r '.run_invocation_id // empty' "$state_file")"
if [[ "$state_invocation_id" != "$invocation_id" ]]; then
  echo "# Hermes Scan Optimizer Cycle"
  echo
  echo "- status: stale_optimizer_state"
  echo "- invocation_id: $invocation_id"
  echo "- state_invocation_id: ${state_invocation_id:-missing}"
  echo "- exit_code: $cycle_exit"
  exit 3
fi

report_path="$(jq -r '.last_report // empty' "$state_file")"
cycle_id="$(jq -r '.last_cycle_id // empty' "$state_file")"
cycle_status="$(jq -r '.last_status // empty' "$state_file")"
last_commit="$(jq -r '.last_commit // empty' "$state_file")"
okx_run_id="$(jq -r '.okx_run_id // empty' "$state_file")"
local_run_id="$(jq -r '.local_run_id // empty' "$state_file")"
okx_run_status="$(jq -r '.okx_run_status // empty' "$state_file")"
local_run_status="$(jq -r '.local_run_status // empty' "$state_file")"

if [[ $cycle_exit -ne 0 && "$cycle_status" == "running" ]]; then
  echo "# Hermes Scan Optimizer Cycle"
  echo
  echo "- status: incomplete_optimizer_state"
  echo "- invocation_id: $invocation_id"
  echo "- cycle_id: ${cycle_id:-unknown}"
  echo "- exit_code: $cycle_exit"
  exit "$cycle_exit"
fi

printf '# Hermes Scan Optimizer Cycle\n\n'
printf -- '- invocation_id: %s\n' "$invocation_id"
printf -- '- cycle_id: %s\n' "${cycle_id:-unknown}"
printf -- '- status: %s\n' "${cycle_status:-unknown}"
printf -- '- exit_code: %s\n' "$cycle_exit"
printf -- '- okx_run: %s (%s)\n' "${okx_run_id:-unknown}" "${okx_run_status:-unknown}"
printf -- '- local_run: %s (%s)\n' "${local_run_id:-unknown}" "${local_run_status:-unknown}"
printf -- '- commit: %s\n' "${last_commit:-none}"
printf -- '- report: %s\n' "${report_path:-missing}"

if [[ -n "$report_path" && -f "$report_path" ]]; then
  printf '\n## Report Excerpt\n\n```text\n'
  python3 - <<'PY' "$report_path"
import sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace').splitlines()
excerpt = lines[-80:] if len(lines) > 80 else lines
print("\n".join(excerpt))
PY
  printf '```\n'
fi

exit "$cycle_exit"
