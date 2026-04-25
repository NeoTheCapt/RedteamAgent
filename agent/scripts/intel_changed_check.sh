#!/usr/bin/env bash
set -euo pipefail

# intel_changed_check.sh — detect newly added intel.md entries and signal
# the operator to dispatch osint-analyst for CVE/breach/DNS correlation.
#
# Without this, osint-analyst ends up at 0 dispatches per cycle (observed
# pattern across 2 audited engagements): the trigger condition in
# operator-core.md is "parallel with exploit-developer when intel.md
# gains entries", but the operator has no mechanical way to know intel
# grew. vulnerability-analyst silently fills in CVE/breach references
# inline as part of its findings, and the operator never separately
# dispatches osint-analyst for the broader correlation pass.
#
# This helper does the diff mechanically:
#   - counts data rows in intel.md (rows in markdown tables that contain
#     real content, not header / separator / template-empty rows)
#   - compares to .osint-respawn-state.json (previous count, high-water
#     mark)
#   - if intel grew, touches .osint-respawn-required flag listing how
#     many new entries appeared
#
# Operator turn loop should:
#   1. ./scripts/intel_changed_check.sh "$DIR"
#   2. if [[ -f "$DIR/.osint-respawn-required" ]]; then
#        dispatch osint-analyst on the engagement directory
#        rm "$DIR/.osint-respawn-required"
#      fi
#
# Idempotent. Fails open on missing files (returns 0, no flag).

ENG_DIR="${1:?usage: intel_changed_check.sh <engagement_dir>}"
INTEL_MD="$ENG_DIR/intel.md"
STATE_FILE="$ENG_DIR/.osint-respawn-state.json"
FLAG_FILE="$ENG_DIR/.osint-respawn-required"

if [[ ! -f "$INTEL_MD" ]]; then
    exit 0
fi

# Count "filled" data rows. A row is "filled" when:
#   - it starts with `| ` followed by a non-dash, non-pipe character
#   - it's NOT a markdown table separator (`| --- | --- |`)
#   - it's NOT a column-header line (we filter common header tokens)
# This counts content rows across all tables in intel.md without depending
# on which `## Section` they're under.
count_filled_rows() {
    /usr/bin/awk '
        /^\| *-+ *\|/ { next }
        /^\| (Component|Name|Email|Item|Type|CVE|Path|URL|Person|Title|Domain|Value|Source|Notes|Version|Confidence|Affected Component|Breach|Date|Data Types|Record|First Seen|Last Seen|Platform|URL\/Handle|Role\/Context|Field) *\|/ { next }
        /^\| / { count++ }
        END { print count + 0 }
    ' "$1"
}

current_count="$(count_filled_rows "$INTEL_MD")"
current_count=${current_count:-0}

prev_count=0
if [[ -f "$STATE_FILE" ]]; then
    prev_count=$(jq '.last_filled_count // 0' "$STATE_FILE" 2>/dev/null || echo 0)
    prev_count=${prev_count:-0}
fi

if (( current_count > prev_count )); then
    delta=$((current_count - prev_count))
    {
        echo "[osint-respawn] $(date -u +%Y-%m-%dT%H:%M:%SZ) detected $delta new intel.md row(s)"
        echo "[osint-respawn] previous=$prev_count  current=$current_count"
        echo "[osint-respawn] operator should dispatch osint-analyst on the engagement"
        echo "[osint-respawn] target: \$DIR  intel.md path: $INTEL_MD"
    } > "$FLAG_FILE"
    echo "osint-respawn flag written: $FLAG_FILE" >&2
fi

# Update state. NEVER lower last_filled_count: if intel.md was rewritten
# (e.g. report-writer dedup compaction reduces row count), preserve the
# high-water mark so the next genuine increase from the lower count
# doesn't double-fire on rows we already correlated.
new_state_count=$prev_count
if (( current_count > prev_count )); then
    new_state_count=$current_count
fi
jq -n --argjson n "$new_state_count" \
    --argjson cur "$current_count" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{last_filled_count: $n, current_count_observed: $cur, updated_at: $ts}' > "$STATE_FILE"
