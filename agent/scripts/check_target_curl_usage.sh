#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: check_target_curl_usage.sh <engagement_dir>}"
LOG_FILE="$ENG_DIR/log.md"

[[ -f "$LOG_FILE" ]] || { echo "log.md not found in $ENG_DIR" >&2; exit 1; }

if rg -n '^\*\*Warning\*\*: In-scope raw curl bypassed `run_tool curl`' "$LOG_FILE" >/dev/null 2>&1; then
    echo "target curl usage check failed: raw in-scope curl detected in log.md" >&2
    rg -n '^\*\*Warning\*\*: In-scope raw curl bypassed `run_tool curl`' "$LOG_FILE" >&2 || true
    exit 1
fi

echo "target curl usage: ok"
