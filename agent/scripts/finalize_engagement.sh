#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/time.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/scope.sh"

ENG_DIR="${1:?usage: finalize_engagement.sh <engagement_dir>}"
SCOPE_FILE="$ENG_DIR/scope.json"
LOG_FILE="$ENG_DIR/log.md"
REPORT_FILE="$ENG_DIR/report.md"
DB_FILE="$ENG_DIR/cases.db"

[[ -f "$SCOPE_FILE" ]] || { echo "scope.json not found in $ENG_DIR" >&2; exit 1; }
[[ -f "$LOG_FILE" ]] || { echo "log.md not found in $ENG_DIR" >&2; exit 1; }

trim_whitespace() {
    local value="${1:-}"
    printf '%s' "$value" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
}

continuous_target_matches() {
    local configured target hostname rule normalized_rule target_host
    configured="$(trim_whitespace "${REDTEAM_CONTINUOUS_TARGETS:-${CONTINUOUS_OBSERVATION_TARGETS:-}}")"
    [[ -n "$configured" ]] || return 1

    target="$(jq -r '.target // empty' "$SCOPE_FILE" 2>/dev/null || true)"
    hostname="$(jq -r '.hostname // empty' "$SCOPE_FILE" 2>/dev/null || true)"
    target_host="$(python3 - <<'PY' "$target"
from urllib.parse import urlsplit
import sys
value = sys.argv[1].strip()
if not value:
    raise SystemExit(0)
try:
    print(urlsplit(value).hostname or "")
except ValueError:
    print("")
PY
)"

    while IFS= read -r rule; do
        normalized_rule="$(trim_whitespace "$rule")"
        [[ -n "$normalized_rule" ]] || continue

        if [[ "$normalized_rule" == re:* ]]; then
            normalized_rule="${normalized_rule#re:}"
            if [[ "$target" =~ $normalized_rule ]] || [[ -n "$hostname" && "$hostname" =~ $normalized_rule ]] || [[ -n "$target_host" && "$target_host" =~ $normalized_rule ]]; then
                return 0
            fi
            continue
        fi

        if [[ "$normalized_rule" == *'*'* || "$normalized_rule" == *'?'* ]]; then
            if [[ "$target" == $normalized_rule ]] || [[ -n "$hostname" && "$hostname" == $normalized_rule ]] || [[ -n "$target_host" && "$target_host" == $normalized_rule ]]; then
                return 0
            fi
            continue
        fi

        if [[ "$target" == "$normalized_rule" ]] || [[ -n "$hostname" && "$hostname" == "$normalized_rule" ]] || [[ -n "$target_host" && "$target_host" == "$normalized_rule" ]]; then
            return 0
        fi
    done < <(printf '%s\n' "$configured" | tr ',;' '\n')

    return 1
}

observation_interval_seconds() {
    local raw="${OBSERVATION_SECONDS:-300}"
    if [[ "$raw" =~ ^[0-9]+$ ]] && (( raw > 0 )); then
        printf '%s\n' "$raw"
    else
        printf '300\n'
    fi
}

mark_scope_in_progress_for_observation() {
    local tmp_scope
    tmp_scope="$(mktemp "${TMPDIR:-/tmp}/scope-observation.XXXXXX")"
    jq '
      .status = "in_progress"
      | .current_phase = "report"
      | del(.end_time)
      | .phases_completed = (((.phases_completed // []) + ["report"]) | unique)
    ' "$SCOPE_FILE" >"$tmp_scope"
    mv "$tmp_scope" "$SCOPE_FILE"
}

mark_log_in_progress_for_observation() {
    local tmp_log
    tmp_log="$(mktemp "${TMPDIR:-/tmp}/log-observation.XXXXXX")"
    awk '
      /^- \*\*Status\*\*:/ { print "- **Status**: In Progress"; next }
      { print }
    ' "$LOG_FILE" >"$tmp_log"
    mv "$tmp_log" "$LOG_FILE"
}

mark_report_in_progress_for_observation() {
    [[ -f "$REPORT_FILE" ]] || return 0
    local start_time eng_date tmp_report
    start_time="$(jq -r '.start_time // empty' "$SCOPE_FILE" 2>/dev/null || true)"
    if [[ -n "$start_time" ]]; then
        eng_date="$(engagement_header_date_from_utc "$start_time")"
    else
        eng_date="$(engagement_header_date_today)"
    fi
    tmp_report="$(mktemp "${TMPDIR:-/tmp}/report-observation.XXXXXX")"
    awk -v date_line="**Date**: ${eng_date} — In Progress" '
      BEGIN { date_done = 0 }
      /^\*\*Date\*\*:/ {
          print date_line
          date_done = 1
          next
      }
      /^\*\*Target\*\*:/ {
          sub(/\*\*Status\*\*: .*/, "**Status**: In Progress")
          print
          next
      }
      /^\*\*Status\*\*:/ {
          print "**Status**: In Progress"
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
}

continuous_observation_loop() {
    local target interval
    target="$(jq -r '.target // empty' "$SCOPE_FILE" 2>/dev/null || true)"
    interval="$(observation_interval_seconds)"

    trap 'echo "[observation] stopping continuous observation hold for ${target:-unknown target}"; exit 0' INT TERM

    echo "[observation] Continuous observation hold active for ${target:-unknown target} (heartbeat ${interval}s)"
    while true; do
        printf '[observation] %s continuous observation hold active for %s; heartbeat=%ss\n' "$(engagement_now_utc)" "${target:-unknown target}" "$interval"
        sleep "$interval" &
        wait "$!"
    done
}

if continuous_target_matches; then
    mark_scope_in_progress_for_observation
    mark_log_in_progress_for_observation
    mark_report_in_progress_for_observation
    continuous_observation_loop
    exit 0
fi

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
  /^- \*\*Status\*\*:/ { print "- **Status**: Completed"; next }
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
