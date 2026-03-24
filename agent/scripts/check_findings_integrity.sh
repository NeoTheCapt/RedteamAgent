#!/usr/bin/env bash
set -euo pipefail

ENG_DIR="${1:?usage: check_findings_integrity.sh <engagement_dir>}"
FINDINGS_FILE="$ENG_DIR/findings.md"

[[ -f "$FINDINGS_FILE" ]] || { echo "findings.md not found in $ENG_DIR" >&2; exit 1; }

failures=0

report_failure() {
    echo "$*" >&2
    failures=1
}

declared_count="$(
    sed -n 's/^\(- \)\{0,1\}\*\*Finding Count\*\*: \([0-9][0-9]*\)$/\2/p' "$FINDINGS_FILE" | head -1
)"
declared_count="${declared_count:-0}"
actual_count="$(rg -c '^## \[FINDING-[A-Z]{2}-[0-9]{3}\]' "$FINDINGS_FILE" 2>/dev/null || printf '0')"

if [[ "$declared_count" != "$actual_count" ]]; then
    report_failure "Finding count mismatch: declared=$declared_count actual=$actual_count"
fi

duplicate_ids="$(
    rg -o '^## \[(FINDING-[A-Z]{2}-[0-9]{3})\]' "$FINDINGS_FILE" \
        | sed 's/^## \[//; s/\]$//' \
        | sort \
        | uniq -d
)"

if [[ -n "$duplicate_ids" ]]; then
    report_failure "Duplicate finding IDs:"
    while IFS= read -r finding_id; do
        [[ -n "$finding_id" ]] && report_failure "  - $finding_id"
    done <<<"$duplicate_ids"
fi

if [[ "$failures" -ne 0 ]]; then
    exit 1
fi

echo "findings integrity: ok"
