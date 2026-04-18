#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/engagement.sh"
EMIT_RUNTIME_EVENT="$SCRIPT_DIR/emit_runtime_event.sh"

usage() {
  echo "usage: append_log_entry.sh [engagement_dir] <agent> <title> <action> <result>" >&2
  exit 1
}

[ "$#" -ge 4 ] || usage

ENG_DIR="${1:-}"
if [ "$#" -eq 4 ]; then
  RESULT="${4:?}"
  ACTION="${3:?}"
  TITLE="${2:?}"
  AGENT="${1:?}"
  ENG_DIR=""
else
  RESULT="${5:?}"
  ACTION="${4:?}"
  TITLE="${3:?}"
  AGENT="${2:?}"
fi

if [ -z "$ENG_DIR" ]; then
  ENG_DIR="${DIR:-${ENGAGEMENT_DIR:-${ENG_DIR:-}}}"
fi

if [ -z "$ENG_DIR" ]; then
  ENG_DIR="$(resolve_engagement_dir "$(pwd)" || true)"
fi

[ -n "$ENG_DIR" ] || {
  echo "could not resolve engagement directory" >&2
  exit 1
}

LOG_FILE="$ENG_DIR/log.md"
LOCK_FILE="$ENG_DIR/.log.lock"
LOCK_DIR="$ENG_DIR/.log.lock.d"

[[ -f "$LOG_FILE" ]] || {
  echo "log.md not found in $ENG_DIR" >&2
  exit 1
}

trim() {
  local text="$1"
  text="${text//$'\r'/ }"
  text="${text//$'\n'/ }"
  text="$(printf '%s' "$text" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
  printf '%s' "$text"
}

truncate() {
  local text
  text="$(trim "$1")"
  local max_len="$2"
  if [ "${#text}" -le "$max_len" ]; then
    printf '%s' "$text"
  else
    printf '%s...' "${text:0:max_len}"
  fi
}

TIMESTAMP="$(date +%H:%M)"
SHORT_TITLE="$(truncate "$TITLE" 80)"
SHORT_ACTION="$(truncate "$ACTION" 240)"
SHORT_RESULT="$(truncate "$RESULT" 360)"

acquire_lock() {
  local attempts=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 50 ]; then
      echo "failed to acquire log lock: $LOCK_DIR" >&2
      exit 1
    fi
    sleep 0.1
  done
  printf '%s\n' "$$" > "$LOCK_FILE"
}

release_lock() {
  rm -f "$LOCK_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap release_lock EXIT
acquire_lock

{
  printf '\n## [%s] %s — %s\n' "$TIMESTAMP" "$SHORT_TITLE" "$AGENT"
  printf '\n**Action**: %s\n' "$SHORT_ACTION"
  printf '**Result**: %s\n' "$SHORT_RESULT"
} >> "$LOG_FILE"

if [[ -f "$EMIT_RUNTIME_EVENT" ]]; then
  bash "$EMIT_RUNTIME_EVENT" \
    "artifact.updated" \
    "${ORCHESTRATOR_PHASE:-unknown}" \
    "log.md" \
    "$AGENT" \
    "$SHORT_TITLE"
fi
