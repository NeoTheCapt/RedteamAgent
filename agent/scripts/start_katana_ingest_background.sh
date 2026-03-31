#!/usr/bin/env bash
# start_katana_ingest_background.sh — Launch katana_ingest.sh in the background,
# write the PID file, and print the spawned PID.
# Usage: ./scripts/start_katana_ingest_background.sh <engagement_dir> [additional_katana_flags]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/processes.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <engagement_dir> [additional_katana_flags]" >&2
    exit 1
fi

ENGAGEMENT_DIR_RAW="$1"
shift
EXTRA_FLAGS=("$@")

if [[ ! -d "$ENGAGEMENT_DIR_RAW" ]]; then
    echo "ERROR: engagement directory not found: $ENGAGEMENT_DIR_RAW" >&2
    exit 1
fi

if [[ "$ENGAGEMENT_DIR_RAW" = /* ]]; then
    ENGAGEMENT_DIR="$ENGAGEMENT_DIR_RAW"
else
    ENGAGEMENT_DIR="$(cd "$ENGAGEMENT_DIR_RAW" && pwd)"
fi

mkdir -p "$ENGAGEMENT_DIR/scans" "$ENGAGEMENT_DIR/pids"

PID_FILE="$(pid_file_path "$ENGAGEMENT_DIR/pids" "katana_ingest")"
if pid_is_running "$PID_FILE"; then
    cat "$PID_FILE"
    exit 0
fi
rm -f "$PID_FILE"

if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then
    ./scripts/katana_ingest.sh "$ENGAGEMENT_DIR" "${EXTRA_FLAGS[@]}" > "$ENGAGEMENT_DIR/scans/katana_ingest.log" 2>&1 < /dev/null &
else
    ./scripts/katana_ingest.sh "$ENGAGEMENT_DIR" > "$ENGAGEMENT_DIR/scans/katana_ingest.log" 2>&1 < /dev/null &
fi
katana_ingest_pid=$!
printf '%s\n' "$katana_ingest_pid" > "$PID_FILE"
printf '%s\n' "$katana_ingest_pid"
