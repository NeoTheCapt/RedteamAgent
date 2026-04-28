#!/usr/bin/env bash
set -euo pipefail

# compose_partial_report.sh — emit an interim report.md from existing
# engagement artifacts WITHOUT invoking the report-writer subagent.
#
# Why: the report-writer pass at end-of-cycle is the only thing that
# produces report.md today. If the cycle is killed mid-pipeline (timeout,
# Docker outage, operator stop), the engagement leaves zero report
# artifact even when findings.md has 10+ findings on disk. This helper
# composes a thin "best-effort" report from what's already on disk so the
# operator and post-mortem reader never face an empty hand.
#
# Operator should call this AFTER every N findings (recommended: 5) and
# at any controlled stop. The final report-writer pass at end-of-cycle
# overwrites this stub with the full polished report.
#
# Output: <engagement_dir>/report.md (overwrites)
# Marker: <engagement_dir>/report.md.partial (presence indicates stub)
#
# Idempotent. Reads only; the only writes are to report.md and the
# .partial marker. No subagent dispatch.

ENG_DIR="${1:?usage: compose_partial_report.sh <engagement_dir>}"
SCOPE="$ENG_DIR/scope.json"
FINDINGS="$ENG_DIR/findings.md"
INTEL="$ENG_DIR/intel.md"
CASES_DB="$ENG_DIR/cases.db"
REPORT="$ENG_DIR/report.md"
MARKER="$ENG_DIR/report.md.partial"

if [[ ! -f "$SCOPE" ]]; then
    echo "scope.json missing at $SCOPE; cannot compose partial report" >&2
    exit 1
fi

target=$(jq -r '.target // "unknown"' "$SCOPE" 2>/dev/null || echo unknown)
status=$(jq -r '.status // "unknown"' "$SCOPE" 2>/dev/null || echo unknown)
phase=$(jq -r '.current_phase // "unknown"' "$SCOPE" 2>/dev/null || echo unknown)
phases_done=$(jq -r '(.phases_completed // []) | join(", ")' "$SCOPE" 2>/dev/null || echo "")
start_time=$(jq -r '.start_time // .started_at // ""' "$SCOPE" 2>/dev/null || echo "")
finding_count=0
if [[ -f "$FINDINGS" ]]; then
    finding_count=$(/usr/bin/grep -c "^## \[FINDING-" "$FINDINGS" 2>/dev/null || echo 0)
fi

# Stage tally (only if cases.db has the stage column)
stage_summary=""
if [[ -f "$CASES_DB" ]] && sqlite3 "$CASES_DB" "SELECT 1 FROM pragma_table_info('cases') WHERE name='stage';" 2>/dev/null | grep -q 1; then
    stage_summary=$(sqlite3 "$CASES_DB" "SELECT stage || '=' || COUNT(*) FROM cases GROUP BY stage ORDER BY stage;" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
fi

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

{
    cat <<EOF
# Engagement Report (PARTIAL — interim snapshot)

> ⚠️ This is an auto-composed interim report assembled by
> \`compose_partial_report.sh\` from existing artifacts. The final
> polished report will be produced by report-writer at end-of-cycle and
> will overwrite this stub. If you are reading this, the cycle was
> either still running at \`$now\` or was interrupted before
> report-writer fired.

## Engagement Metadata
- target: $target
- start_time: $start_time
- composed_at: $now
- engagement status: $status
- current_phase: $phase
- phases_completed: $phases_done
- finding_count: $finding_count
- pipeline stages: $stage_summary

## Findings (verbatim from findings.md)
EOF

    if [[ -f "$FINDINGS" ]] && [[ -s "$FINDINGS" ]]; then
        echo
        cat "$FINDINGS"
    else
        echo
        echo "_(no findings.md content yet)_"
    fi

    echo
    echo "## Intel (verbatim from intel.md)"
    if [[ -f "$INTEL" ]] && [[ -s "$INTEL" ]]; then
        echo
        cat "$INTEL"
    else
        echo
        echo "_(no intel.md content yet)_"
    fi

    cat <<EOF

---
_End of partial report. Composed from on-disk artifacts only. No
analysis, no chain hypothesis, no severity reassessment beyond what
each finding's author wrote. Run report-writer for the full version._
EOF
} > "$REPORT"

touch "$MARKER"
echo "partial report composed: $REPORT (findings=$finding_count stages=[$stage_summary])"
