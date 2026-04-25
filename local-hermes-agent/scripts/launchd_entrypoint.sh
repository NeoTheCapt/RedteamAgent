#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
mkdir -p "$STATE_DIR"
ENV_FILE="${LOCAL_HERMES_ENV_FILE:-$STATE_DIR/scheduler.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "scheduler env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

rotate_log() {
  local log_file="$1"
  local max_bytes="${HERMES_LOG_MAX_BYTES:-10485760}"  # 10MB default
  if [[ -f "$log_file" ]]; then
    local size
    size="$(stat -f%z "$log_file" 2>/dev/null || echo 0)"
    if (( size > max_bytes )); then
      mv "$log_file" "${log_file}.1"
    fi
  fi
}

rotate_log "$ROOT_DIR/logs/launchd-stdout.log"
rotate_log "$ROOT_DIR/logs/launchd-stderr.log"

exec "$ROOT_DIR/scripts/run_cycle.sh"
