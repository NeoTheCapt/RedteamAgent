#!/usr/bin/env bash
# audit_finding.sh — shared helpers for audit report construction
# Source this file; do not execute directly.
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/audit_finding.sh"
#   audit_init_report "$cycle_id" "$source_tag"
#   audit_append_finding "API-001" "high" "orch_api" "GET /auth/me returns 500" '{"file":"app/api/auth.py","line":73}'
#   audit_record_pass
#   audit_finalize_report
#
# Findings are accumulated in a newline-delimited JSON file (_FINDING_STAGING)
# which is safe to write across shell calls without quoting worries.

REPORT_PATH="${REPORT_PATH:-}"
_AUDIT_PASS_COUNT=0
_AUDIT_FAIL_COUNT=0
_AUDIT_FINDINGS_COUNT=0
_FINDING_STAGING=""
_AUDIT_COUNTER_FILE=""   # temp file for cross-subshell finding counter

# audit_init_report <cycle_id> <source_tag>
# Creates the output JSON skeleton and staging file.
audit_init_report() {
    local cycle_id="${1:?cycle_id required}"
    local source_tag="${2:-unknown}"
    local root_dir
    root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    local audit_dir="$root_dir/audit-reports/$cycle_id"
    mkdir -p "$audit_dir"

    if [[ -z "$REPORT_PATH" ]]; then
        REPORT_PATH="$audit_dir/${source_tag}.json"
        export REPORT_PATH
    fi

    _AUDIT_PASS_COUNT=0
    _AUDIT_FAIL_COUNT=0
    _AUDIT_FINDINGS_COUNT=0
    _FINDING_STAGING="$(mktemp)"
    _AUDIT_COUNTER_FILE="$(mktemp)"
    echo "0" > "$_AUDIT_COUNTER_FILE"
    export _FINDING_STAGING _AUDIT_COUNTER_FILE

    # Write skeleton JSON
    python3 -c "
import json
from datetime import datetime, timezone
data = {
    'cycle_id': '$cycle_id',
    'source_tag': '$source_tag',
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'findings': [],
    'pass_count': 0,
    'fail_count': 0
}
import sys
sys.stdout.write(json.dumps(data, indent=2) + '\n')
" > "$REPORT_PATH"
}

# audit_append_finding <id> <severity> <category> <summary> <evidence_json>
# Writes one finding as a JSON line to the staging file.
audit_append_finding() {
    local id="${1:?finding id required}"
    local severity="${2:?severity required}"
    local category="${3:?category required}"
    local summary="$4"
    local evidence="${5:-{\}}"

    _AUDIT_FAIL_COUNT=$(( _AUDIT_FAIL_COUNT + 1 ))
    _AUDIT_FINDINGS_COUNT=$(( _AUDIT_FINDINGS_COUNT + 1 ))

    if [[ -z "$_FINDING_STAGING" ]] || [[ ! -f "$_FINDING_STAGING" ]]; then
        _FINDING_STAGING="$(mktemp)"
        export _FINDING_STAGING
    fi

    # Write one JSON object per line to staging file — avoids shell quoting issues
    python3 -c "
import json, sys
finding = {
    'id': sys.argv[1],
    'category': sys.argv[3],
    'severity': sys.argv[2],
    'summary': sys.argv[4],
    'evidence': json.loads(sys.argv[5]) if sys.argv[5].strip().startswith('{') else {'raw': sys.argv[5]},
    'suggested_fix_path': ''
}
print(json.dumps(finding, ensure_ascii=False))
" "$id" "$severity" "$category" "$summary" "$evidence" >> "$_FINDING_STAGING"
}

# audit_record_pass
# Increments pass_count only.
audit_record_pass() {
    _AUDIT_PASS_COUNT=$(( _AUDIT_PASS_COUNT + 1 ))
}

# audit_finalize_report
# Merges findings from staging file into the report JSON.
audit_finalize_report() {
    [[ -n "$REPORT_PATH" ]] || { echo "audit_finalize_report: REPORT_PATH not set" >&2; return 1; }

    local staging="${_FINDING_STAGING:-}"
    local pass_count="${_AUDIT_PASS_COUNT:-0}"
    local fail_count="${_AUDIT_FAIL_COUNT:-0}"

    python3 - "$REPORT_PATH" "${staging:-/dev/null}" "$pass_count" "$fail_count" <<'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime, timezone

report_path = Path(sys.argv[1])
staging_path = sys.argv[2]
pass_count = int(sys.argv[3])
fail_count = int(sys.argv[4])

try:
    data = json.loads(report_path.read_text(encoding="utf-8"))
except Exception:
    data = {}

findings = []
staging = Path(staging_path)
if staging.exists() and staging.stat().st_size > 0:
    for line in staging.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.stderr.write(f"audit_finalize_report: skipping malformed line: {e}\n")

data["findings"] = findings
data["pass_count"] = pass_count
data["fail_count"] = fail_count
data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
sys.stderr.write(f"audit_finalize_report: wrote {len(findings)} findings to {report_path}\n")
PYEOF

    # Clean up staging and counter files
    [[ -n "$staging" && -f "$staging" ]] && rm -f "$staging" || true
    _FINDING_STAGING=""
    local counter_file="${_AUDIT_COUNTER_FILE:-}"
    [[ -n "$counter_file" && -f "$counter_file" ]] && rm -f "$counter_file" || true
    _AUDIT_COUNTER_FILE=""
}

# audit_next_id <prefix>
# Returns the next sequential finding ID using a cross-subshell file counter.
# Safe to call inside $() subshells.
audit_next_id() {
    local prefix="${1:-FND}"
    local counter_file="${_AUDIT_COUNTER_FILE:-}"
    local n=0
    if [[ -n "$counter_file" && -f "$counter_file" ]]; then
        n="$(cat "$counter_file" 2>/dev/null || echo 0)"
        n=$(( n + 1 ))
        echo "$n" > "$counter_file"
    else
        n=$(( _AUDIT_FINDINGS_COUNT + 1 ))
    fi
    printf '%s-%03d' "$prefix" "$n"
}
