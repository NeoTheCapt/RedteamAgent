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

read -r successful_rows recoverable_rows malformed_rows <<<"$(python3 - <<'PY' "$KATANA_OUTPUT"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
successful = 0
recoverable = 0
malformed = 0

for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
    line = raw_line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        malformed += 1
        continue

    endpoint = str(
        row.get('request', {}).get('endpoint')
        or row.get('endpoint')
        or row.get('url')
        or ''
    )
    if not endpoint:
        continue

    error = str(row.get('error') or '')
    if not error:
        successful += 1
        continue

    if 'hybrid: could not get dom' in error or 'hybrid: response is nil' in error:
        recoverable += 1

print(successful, recoverable, malformed)
PY
)"

if [[ "${successful_rows:-0}" -eq 0 && "${recoverable_rows:-0}" -eq 0 ]]; then
    echo "collection health failed: katana output contains no successful or recoverable discovery rows" >&2
    if [[ "${malformed_rows:-0}" -gt 0 ]]; then
        echo "collection health note: ignored $malformed_rows malformed katana output line(s)" >&2
    fi
    [[ -f "$KATANA_LOG" ]] && tail -50 "$KATANA_LOG" >&2 || true
    tail -20 "$KATANA_OUTPUT" >&2 || true
    exit 1
fi

if [[ "${successful_rows:-0}" -eq 0 && "${recoverable_rows:-0}" -gt 0 ]]; then
    echo "collection health: ok (recoverable-only crawl output: $recoverable_rows discovery rows despite render/fetch errors; ignored ${malformed_rows:-0} malformed line(s))"
    exit 0
fi

echo "collection health: ok (successful=$successful_rows recoverable=$recoverable_rows malformed=${malformed_rows:-0})"
