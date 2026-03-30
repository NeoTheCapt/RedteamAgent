#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: check_katana_usage.sh <engagement_dir>}"
LOG_FILE="$ENG_DIR/log.md"

[[ -f "$LOG_FILE" ]] || { echo "log.md not found in $ENG_DIR" >&2; exit 1; }

if rg -n '^\*\*Warning\*\*: Raw katana launch bypassed `start_katana`/`katana_ingest\.sh`' "$LOG_FILE" >/dev/null 2>&1; then
    echo "katana usage check failed: raw katana launch detected in log.md" >&2
    rg -n '^\*\*Warning\*\*: Raw katana launch bypassed `start_katana`/`katana_ingest\.sh`' "$LOG_FILE" >&2 || true
    exit 1
fi

echo "katana usage: ok"
