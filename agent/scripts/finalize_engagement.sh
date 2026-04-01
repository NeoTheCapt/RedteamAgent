#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/time.sh"

ENG_DIR="${1:?usage: finalize_engagement.sh <engagement_dir>}"
SCOPE_FILE="$ENG_DIR/scope.json"
LOG_FILE="$ENG_DIR/log.md"
REPORT_FILE="$ENG_DIR/report.md"
DB_FILE="$ENG_DIR/cases.db"

[[ -f "$SCOPE_FILE" ]] || { echo "scope.json not found in $ENG_DIR" >&2; exit 1; }
[[ -f "$LOG_FILE" ]] || { echo "log.md not found in $ENG_DIR" >&2; exit 1; }

END_TIME="$(engagement_now_utc)"
START_TIME="$(jq -r '.start_time // empty' "$SCOPE_FILE" 2>/dev/null || true)"
if [[ -n "$START_TIME" ]]; then
    ENG_DATE="$(engagement_header_date_from_utc "$START_TIME")"
else
    ENG_DATE="$(engagement_header_date_today)"
fi

tmp_scope="$(mktemp "${TMPDIR:-/tmp}/scope-finalize.XXXXXX")"
jq --arg end_time "$END_TIME" '
  .status = "complete"
  | .current_phase = "complete"
  | .end_time = $end_time
  | .phases_completed = (((.phases_completed // []) + ["report"]) | unique)
' "$SCOPE_FILE" >"$tmp_scope"
mv "$tmp_scope" "$SCOPE_FILE"

tmp_log="$(mktemp "${TMPDIR:-/tmp}/log-finalize.XXXXXX")"
awk '
  /^\- \*\*Status\*\*:/ { print "- **Status**: Completed"; next }
  { print }
' "$LOG_FILE" >"$tmp_log"
mv "$tmp_log" "$LOG_FILE"

if [[ -f "$REPORT_FILE" ]]; then
    tmp_report="$(mktemp "${TMPDIR:-/tmp}/report-finalize.XXXXXX")"
    awk -v date_line="**Date**: ${ENG_DATE} — Completed" '
      BEGIN { date_done = 0; target_done = 0 }
      /^\*\*Date\*\*:/ {
          print date_line
          date_done = 1
          next
      }
      /^\*\*Target\*\*:/ {
          sub(/\*\*Status\*\*: .*/, "**Status**: Completed")
          print
          target_done = 1
          next
      }
      /^\*\*Status\*\*:/ {
          print "**Status**: Completed"
          next
      }
      { print }
      END {
          if (!date_done) {
              print date_line
          }
      }
    ' "$REPORT_FILE" >"$tmp_report"
    mv "$tmp_report" "$REPORT_FILE"
fi

rm -f "$ENG_DIR"/tmp-*.md

if [[ -f "$DB_FILE" ]]; then
    printf '.timeout 5000\nPRAGMA wal_checkpoint(TRUNCATE);\n' | sqlite3 "$DB_FILE" >/dev/null
    rm -f "$DB_FILE-wal" "$DB_FILE-shm"
fi
