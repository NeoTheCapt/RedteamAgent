#!/usr/bin/env bash
# audit_orchestrator_logs.sh — scan logs for anomalies and write findings
# Usage: bash audit_orchestrator_logs.sh <cycle_id>
#
# Scans:
#   - orchestrator/.run/orchestrator.log (uvicorn stderr)
#   - Recent engagements' runtime/process.log (last 10 runs)
#   - ~/.hermes/logs/*.log (last 5 Hermes agent logs)
#
# Output: local-hermes-agent/audit-reports/<cycle_id>/logs.json

set -euo pipefail
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
CYCLE_ID="${1:?Usage: audit_orchestrator_logs.sh <cycle_id>}"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/audit_finding.sh"

AUDIT_DIR="$ROOT_DIR/audit-reports/$CYCLE_ID"
export REPORT_PATH="$AUDIT_DIR/logs.json"

mkdir -p "$AUDIT_DIR"
audit_init_report "$CYCLE_ID" "logs"

# --- configuration ----------------------------------------------------------

ORCH_LOG_PATH="${ORCH_LOG_PATH:-$REPO_ROOT/orchestrator/.run/orchestrator.log}"
ORCH_DATA_DIR="${REDTEAM_ORCHESTRATOR_DATA_DIR:-$REPO_ROOT/orchestrator/backend/data}"
SCAN_LINES="${LOG_SCAN_LINES:-2000}"
MAX_RUNS_TO_SCAN=10
MAX_HERMES_LOGS=5

# Regex patterns for anomalies
PATTERNS=(
    "Traceback"
    "ERROR"
    "CRITICAL"
    "sqlite3.OperationalError: database is locked"
    "RuntimeError"
    "TimeoutError"
)
HTTP_5XX_PATTERN='" [5][0-9][0-9] '
REPEATED_WARNING_THRESHOLD=10

# --- helpers ----------------------------------------------------------------

_scan_file() {
    local filepath="$1" label="$2" context_lines=5
    [[ -f "$filepath" ]] || return 0

    local tail_content
    tail_content="$(tail -n "$SCAN_LINES" "$filepath" 2>/dev/null || true)"
    [[ -n "$tail_content" ]] || return 0

    local found_any=0

    for pattern in "${PATTERNS[@]}"; do
        local count
        count="$(printf '%s' "$tail_content" | grep -c -- "$pattern" 2>/dev/null || true)"
        if (( count > 0 )); then
            found_any=1
            local excerpt
            excerpt="$(printf '%s' "$tail_content" | grep -m 5 -A "$context_lines" "$pattern" 2>/dev/null | head -n 30 | tr '\n' '|' | sed 's/|$//' || true)"
            local fnd_id
            fnd_id="$(audit_next_id "LOG")"
            local severity="medium"
            if [[ "$pattern" == "CRITICAL" || "$pattern" == "sqlite3.OperationalError: database is locked" ]]; then
                severity="high"
            elif [[ "$pattern" == "Traceback" || "$pattern" == "RuntimeError" ]]; then
                severity="high"
            fi
            audit_append_finding "$fnd_id" "$severity" "orch_log" \
                "$label: found $count occurrence(s) of '$pattern'" \
                "{\"file\": \"$filepath\", \"pattern\": $(printf '%s' "$pattern" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'), \"count\": $count, \"excerpt\": $(printf '%s' "$excerpt" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}"
            echo "[FAIL] $label: $count x '$pattern' in $(basename "$filepath")" >&2
        fi
    done

    # HTTP 5xx check (uvicorn access log format)
    local http5xx_count
    http5xx_count="$(printf '%s' "$tail_content" | grep -cP -- "$HTTP_5XX_PATTERN" 2>/dev/null || true)"
    if (( http5xx_count > 0 )); then
        found_any=1
        local excerpt5xx
        excerpt5xx="$(printf '%s' "$tail_content" | grep -P "$HTTP_5XX_PATTERN" | tail -n 5 | tr '\n' '|' | sed 's/|$//' || true)"
        local fnd_id
        fnd_id="$(audit_next_id "LOG")"
        audit_append_finding "$fnd_id" "high" "orch_log" \
            "$label: found $http5xx_count HTTP 5xx response(s) in log" \
            "{\"file\": \"$filepath\", \"pattern\": \"HTTP 5xx\", \"count\": $http5xx_count, \"excerpt\": $(printf '%s' "$excerpt5xx" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}"
        echo "[FAIL] $label: $http5xx_count HTTP 5xx lines in $(basename "$filepath")" >&2
    fi

    # Repeated warning check (any single line pattern repeated > threshold)
    local repeated_line
    repeated_line="$(printf '%s' "$tail_content" | grep -i "warning\|warn" 2>/dev/null | sort | uniq -c | sort -rn | awk -v t="$REPEATED_WARNING_THRESHOLD" '$1 > t {print $1, substr($0, index($0,$2))}' | head -3 || true)"
    if [[ -n "$repeated_line" ]]; then
        found_any=1
        local fnd_id
        fnd_id="$(audit_next_id "LOG")"
        audit_append_finding "$fnd_id" "low" "orch_log" \
            "$label: repeated warning detected (>$REPEATED_WARNING_THRESHOLD occurrences)" \
            "{\"file\": \"$filepath\", \"pattern\": \"repeated_warning\", \"lines\": $(printf '%s' "$repeated_line" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}"
        echo "[FAIL] $label: repeated warnings in $(basename "$filepath")" >&2
    fi

    if (( found_any == 0 )); then
        audit_record_pass
        echo "[PASS] $label: no anomalies in $(basename "$filepath") (last $SCAN_LINES lines)" >&2
    fi
}

# --- scan orchestrator log --------------------------------------------------

if [[ -f "$ORCH_LOG_PATH" ]]; then
    _scan_file "$ORCH_LOG_PATH" "orchestrator"
else
    # Try common alternative paths
    for alt in \
        "$REPO_ROOT/orchestrator/logs/orchestrator.log" \
        "$REPO_ROOT/orchestrator/backend/orchestrator.log"; do
        if [[ -f "$alt" ]]; then
            _scan_file "$alt" "orchestrator"
            break
        fi
    done
    echo "[INFO] orchestrator log not found at $ORCH_LOG_PATH; skipping" >&2
fi

# --- scan recent engagement process logs ------------------------------------

engagements_root=""
for candidate in \
    "$ORCH_DATA_DIR/engagements" \
    "$REPO_ROOT/orchestrator/backend/data/engagements" \
    "/var/folders"; do
    if [[ -d "$candidate" ]]; then
        engagements_root="$candidate"
        break
    fi
done

if [[ -n "$engagements_root" && -d "$engagements_root" ]]; then
    # Find the N most recently modified process.log files (bash 3.2 compatible)
    found_any_proc=0
    while IFS= read -r proc_log; do
        [[ -z "$proc_log" ]] && continue
        found_any_proc=1
        local_label="engagement:$(basename "$(dirname "$(dirname "$proc_log")")")"
        _scan_file "$proc_log" "$local_label"
    done < <(find "$engagements_root" -name "process.log" -maxdepth 6 \
        -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -n "$MAX_RUNS_TO_SCAN" | awk '{print $2}' || true)

    if [[ "$found_any_proc" -eq 0 ]]; then
        echo "[INFO] no engagement process.log files found under $engagements_root" >&2
    fi
else
    echo "[INFO] engagements root not found; skipping engagement log scan" >&2
fi

# --- scan Hermes agent logs (opt-in) ----------------------------------------
#
# Hermes's own logs are NOT scoped to RedteamOpencode: they capture the auditor
# agent's session (tool use, checkpoint_manager, gateway delivery, etc.). During
# an auditor cycle those logs are actively being written by Hermes itself, so
# every cycle re-generates "findings" about checkpoint-manager errors, git
# add failures on transient sqlite WAL files, etc. — none of which are
# actionable as RedteamOpencode product bugs. Disabled by default; set
# AUDIT_INCLUDE_HERMES_LOGS=1 to re-enable for targeted debugging.

if [[ "${AUDIT_INCLUDE_HERMES_LOGS:-0}" == "1" ]]; then
    hermes_log_dir="${HERMES_LOG_DIR:-$HOME/.hermes/logs}"
    if [[ -d "$hermes_log_dir" ]]; then
        found_any_hermes=0
        while IFS= read -r hlog; do
            [[ -z "$hlog" ]] && continue
            found_any_hermes=1
            _scan_file "$hlog" "hermes:$(basename "$hlog")"
        done < <(find "$hermes_log_dir" -name "*.log" -maxdepth 2 \
            -exec stat -f '%m %N' {} \; 2>/dev/null | sort -rn | head -n "$MAX_HERMES_LOGS" | awk '{print $2}' || true)

        if [[ "$found_any_hermes" -eq 0 ]]; then
            echo "[INFO] no Hermes log files found under $hermes_log_dir" >&2
        fi
    else
        echo "[INFO] Hermes log dir not found at $hermes_log_dir; skipping" >&2
    fi
else
    echo "[INFO] skipping Hermes log scan (AUDIT_INCLUDE_HERMES_LOGS=0 by default)" >&2
fi

# --- finalize ---------------------------------------------------------------

audit_finalize_report
echo "[audit_orchestrator_logs] complete: pass=$_AUDIT_PASS_COUNT fail=$_AUDIT_FAIL_COUNT → $REPORT_PATH" >&2
