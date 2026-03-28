#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: check_collection_health.sh <engagement_dir>}"
SCANS_DIR="$ENG_DIR/scans"
KATANA_LOG="$SCANS_DIR/katana_ingest.log"
KATANA_OUTPUT="$SCANS_DIR/katana_output.jsonl"
KATANA_PID="$ENG_DIR/pids/katana.pid"

attempted=0
[[ -f "$KATANA_LOG" ]] && attempted=1
[[ -f "$KATANA_PID" ]] && attempted=1
[[ -f "$KATANA_OUTPUT" ]] && attempted=1

if [[ "$attempted" -eq 0 ]]; then
    echo "collection health: ok (katana not started)"
    exit 0
fi

if [[ ! -s "$KATANA_OUTPUT" ]]; then
    echo "collection health failed: katana was started but scans/katana_output.jsonl is missing or empty" >&2
    [[ -f "$KATANA_LOG" ]] && tail -50 "$KATANA_LOG" >&2 || true
    exit 1
fi

successful_rows="$(
    jq -r 'select(((.error // "") | tostring | length) == 0 and (((.request.endpoint // .endpoint // .url // "") | tostring | length) > 0)) | 1' \
        "$KATANA_OUTPUT" 2>/dev/null | wc -l | tr -d ' '
)"

if [[ "${successful_rows:-0}" -eq 0 ]]; then
    echo "collection health failed: katana output only contains errored rows and no successful crawl results" >&2
    [[ -f "$KATANA_LOG" ]] && tail -50 "$KATANA_LOG" >&2 || true
    tail -20 "$KATANA_OUTPUT" >&2 || true
    exit 1
fi

echo "collection health: ok"
