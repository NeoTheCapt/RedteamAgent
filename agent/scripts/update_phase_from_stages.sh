#!/usr/bin/env bash
set -euo pipefail

# update_phase_from_stages.sh — derive scope.json.current_phase from
# the stage distribution in cases.db. Replaces hand-written `jq` calls
# that flipped current_phase based on hard-coded sequencing.
#
# Mapping:
#   - any in-flight processing for recon-specialist / source-analyzer
#     during initial discovery → recon
#   - cases.db growing rapidly + most cases at ingested → collect
#   - active stages (ingested|source_analyzed|vuln_confirmed) > 0 and
#     no exploit-developer in flight → consume_test
#   - any case at vuln_confirmed OR exploit-developer in flight → exploit
#   - report-writer running, no other in-flight, no active stages → report
#   - everything terminal → complete
#
# Idempotent. Only updates scope.json when the derived phase changes.

ENG_DIR="${1:?usage: update_phase_from_stages.sh <engagement_dir>}"
SCOPE_JSON="$ENG_DIR/scope.json"
CASES_DB="$ENG_DIR/cases.db"

if [[ ! -f "$SCOPE_JSON" ]]; then
    echo "scope.json missing at $SCOPE_JSON" >&2
    exit 1
fi
if [[ ! -f "$CASES_DB" ]]; then
    echo "cases.db missing at $CASES_DB" >&2
    exit 1
fi

# Stage tallies (idempotent — handles missing column on legacy DBs).
sql() { sqlite3 "$CASES_DB" ".timeout 3000" "$1" 2>/dev/null || true; }

# If stage column doesn't exist yet, default to legacy phase logic.
HAS_STAGE=$(sql "SELECT COUNT(*) FROM pragma_table_info('cases') WHERE name='stage';")
if [[ "${HAS_STAGE:-0}" != "1" ]]; then
    echo "stage column not present in cases.db; phase update skipped (legacy db)" >&2
    exit 0
fi

ACTIVE=$(sql "SELECT COUNT(*) FROM cases WHERE stage IN ('ingested','source_analyzed','vuln_confirmed');")
PROCESSING=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing';")
VULN_CONFIRMED=$(sql "SELECT COUNT(*) FROM cases WHERE stage='vuln_confirmed';")
EXPLOIT_IN_FLIGHT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent LIKE 'exploit-developer%';")
RECON_IN_FLIGHT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent LIKE 'recon-specialist%';")
REPORT_IN_FLIGHT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent LIKE 'report-writer%';")
TOTAL=$(sql "SELECT COUNT(*) FROM cases;")
INGESTED=$(sql "SELECT COUNT(*) FROM cases WHERE stage='ingested';")

derived="consume_test"
if [[ "${TOTAL:-0}" -eq 0 ]] || [[ "${RECON_IN_FLIGHT:-0}" -gt 0 ]]; then
    derived="recon"
elif [[ "${REPORT_IN_FLIGHT:-0}" -gt 0 ]] && [[ "${ACTIVE:-0}" -eq 0 ]]; then
    derived="report"
elif [[ "${ACTIVE:-0}" -eq 0 ]] && [[ "${PROCESSING:-0}" -eq 0 ]]; then
    derived="complete"
elif [[ "${VULN_CONFIRMED:-0}" -gt 0 ]] || [[ "${EXPLOIT_IN_FLIGHT:-0}" -gt 0 ]]; then
    derived="exploit"
elif [[ "${INGESTED:-0}" -eq "${ACTIVE:-0}" ]] && [[ "${ACTIVE:-0}" -gt 0 ]] && [[ "${PROCESSING:-0}" -eq 0 ]]; then
    # All active cases haven't been touched yet — still in collect-style ingest.
    derived="collect"
fi

# Read current and patch only if changed.
current="$(jq -r '.current_phase // ""' "$SCOPE_JSON" 2>/dev/null || echo "")"
if [[ "$current" == "$derived" ]]; then
    exit 0
fi

# Phase ordinality (for monotonic phases_completed accumulation).
# Only ADD predecessors when phase ADVANCES — if the derived phase
# regresses (e.g. report -> exploit when a new vuln_confirmed lands
# after report-writer ran), leave phases_completed alone so existing
# entries don't lie about what's "complete". Code that consumes
# phases_completed (finalize_engagement.sh) treats it as
# "phases that have been entered at least once," which is correct
# under monotonic-only updates.
phase_index() {
    case "$1" in
        ""|recon) echo 0 ;;
        collect) echo 1 ;;
        consume_test) echo 2 ;;
        exploit) echo 3 ;;
        report) echo 4 ;;
        complete) echo 5 ;;
        *) echo -1 ;;
    esac
}
current_idx=$(phase_index "$current")
derived_idx=$(phase_index "$derived")

tmp="$(mktemp "${TMPDIR:-/tmp}/scope-XXXXXX.json")"
if (( derived_idx > current_idx )); then
    # Forward transition — backfill predecessors.
    jq --arg phase "$derived" '
        .current_phase = $phase
        | .phases_completed = (
            ((.phases_completed // []) +
                (if $phase == "collect" then ["recon"]
                 elif $phase == "consume_test" then ["recon","collect"]
                 elif $phase == "exploit" then ["recon","collect","consume_test"]
                 elif $phase == "report" then ["recon","collect","consume_test","exploit"]
                 elif $phase == "complete" then ["recon","collect","consume_test","exploit","report"]
                 else [] end))
            | unique
          )
    ' "$SCOPE_JSON" > "$tmp"
else
    # Regression (e.g. new vuln_confirmed after report). Update
    # current_phase only; preserve phases_completed.
    jq --arg phase "$derived" '.current_phase = $phase' "$SCOPE_JSON" > "$tmp"
fi

mv "$tmp" "$SCOPE_JSON"
echo "phase: $current -> $derived  (active=$ACTIVE processing=$PROCESSING vuln_confirmed=$VULN_CONFIRMED)" >&2
