#!/usr/bin/env bash
set -euo pipefail

# test_stage_set_consistency.sh — D7 cross-file stage-set drift check.
#
# The streaming pipeline's set of terminal vs. active stages is encoded
# in FOUR independent locations. Any drift between them produces a
# false-positive `incomplete_stop` / `queue_stalled` (orchestrator side)
# or a false `phase=complete` derivation (agent side). Observed twice
# in 2026-04-26:
#
#   1. After streaming pipeline rolled out, run 730 was misclassified as
#      `incomplete_stop` because launcher.py counted api_tested/pending
#      rows as "active pending undispatched work". Fixed by 2d0610e.
#   2. After auditor commit 2a1644a moved source_analyzed from active
#      to terminal in dispatcher.sh + update_phase_from_stages.sh, the
#      orchestrator backend's _TERMINAL_CASE_STAGES still had the old
#      4-tuple — same bug class, different stage. Fixed by dd9a103.
#
# This test is the permanent guard against the 3rd recurrence: parse
# the canonical set from dispatcher.sh and require the other three
# definitions to match.
#
# Exit 0 = pass, 1 = drift, 2 = harness error. Run from repo root.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

DISPATCHER="$ROOT/agent/scripts/dispatcher.sh"
UPDATE_PHASE="$ROOT/agent/scripts/update_phase_from_stages.sh"
LAUNCHER_PY="$ROOT/orchestrator/backend/app/services/launcher.py"
RUNS_PY="$ROOT/orchestrator/backend/app/services/runs.py"

for f in "$DISPATCHER" "$UPDATE_PHASE" "$LAUNCHER_PY" "$RUNS_PY"; do
    if [[ ! -f "$f" ]]; then
        echo "FATAL: required source file missing: $f" >&2
        exit 2
    fi
done

violations=0

# --- Extract the canonical sets from dispatcher.sh ---
# dispatcher.sh stats-by-stage block has two SQL clauses we parse:
#   active   : "stage IN ('ingested','vuln_confirmed','fuzz_pending')"
#   terminal : "stage IN ('source_analyzed','clean','exploited','errored','api_tested')"
#
# We extract the comma-joined stage list from each, normalize whitespace and
# quote style, and treat the resulting set (sorted) as the canonical truth.

parse_stage_set() {
    # Read stdin; output sorted unique stage tokens, one per line.
    /usr/bin/grep -oE "'[a-z_]+'" \
        | /usr/bin/tr -d "'" \
        | /usr/bin/sort -u
}

# Pull the lines from dispatcher.sh stats-by-stage block.
DISPATCHER_ACTIVE_LINE=$(/usr/bin/grep -m1 "stage IN ('ingested'" "$DISPATCHER" || true)
DISPATCHER_TERMINAL_LINE=$(/usr/bin/grep -m1 "stage IN ('source_analyzed'" "$DISPATCHER" || true)

if [[ -z "$DISPATCHER_ACTIVE_LINE" ]]; then
    echo "FATAL: dispatcher.sh has no recognizable active stage IN clause; parser needs an update" >&2
    exit 2
fi
if [[ -z "$DISPATCHER_TERMINAL_LINE" ]]; then
    echo "FATAL: dispatcher.sh has no recognizable terminal stage IN clause; parser needs an update" >&2
    exit 2
fi

DISPATCHER_ACTIVE=$(printf '%s\n' "$DISPATCHER_ACTIVE_LINE" | parse_stage_set)
DISPATCHER_TERMINAL=$(printf '%s\n' "$DISPATCHER_TERMINAL_LINE" | parse_stage_set)

# --- D7-A: update_phase_from_stages.sh ACTIVE clause must match dispatcher.sh active set ---
UPDATE_PHASE_ACTIVE_LINE=$(/usr/bin/grep -m1 "^ACTIVE=" "$UPDATE_PHASE" || true)
if [[ -z "$UPDATE_PHASE_ACTIVE_LINE" ]]; then
    echo "[D7-A] FATAL: update_phase_from_stages.sh has no ACTIVE= line; parser needs an update" >&2
    violations=$((violations + 1))
else
    UPDATE_PHASE_ACTIVE=$(printf '%s\n' "$UPDATE_PHASE_ACTIVE_LINE" | parse_stage_set)
    if [[ "$UPDATE_PHASE_ACTIVE" != "$DISPATCHER_ACTIVE" ]]; then
        echo "[D7-A] update_phase_from_stages.sh ACTIVE set drift" >&2
        echo "      dispatcher.sh:   $(printf '%s' "$DISPATCHER_ACTIVE" | tr '\n' ' ')" >&2
        echo "      update_phase.sh: $(printf '%s' "$UPDATE_PHASE_ACTIVE" | tr '\n' ' ')" >&2
        violations=$((violations + 1))
    fi
fi

# --- D7-B: launcher.py _TERMINAL_CASE_STAGES must match dispatcher.sh terminal set ---
LAUNCHER_TERMINAL_LINE=$(/usr/bin/grep -m1 "^_TERMINAL_CASE_STAGES = " "$LAUNCHER_PY" || true)
if [[ -z "$LAUNCHER_TERMINAL_LINE" ]]; then
    echo "[D7-B] FATAL: launcher.py has no _TERMINAL_CASE_STAGES line; parser needs an update" >&2
    violations=$((violations + 1))
else
    LAUNCHER_TERMINAL=$(printf '%s\n' "$LAUNCHER_TERMINAL_LINE" | /usr/bin/grep -oE '"[a-z_]+"' | /usr/bin/tr -d '"' | /usr/bin/sort -u)
    if [[ "$LAUNCHER_TERMINAL" != "$DISPATCHER_TERMINAL" ]]; then
        echo "[D7-B] launcher.py _TERMINAL_CASE_STAGES drift" >&2
        echo "      dispatcher.sh terminal: $(printf '%s' "$DISPATCHER_TERMINAL" | tr '\n' ' ')" >&2
        echo "      launcher.py terminal:   $(printf '%s' "$LAUNCHER_TERMINAL" | tr '\n' ' ')" >&2
        violations=$((violations + 1))
    fi
fi

# --- D7-C: runs.py inline terminal_stages must match dispatcher.sh terminal set ---
RUNS_TERMINAL_LINE=$(/usr/bin/grep -m1 "terminal_stages = (" "$RUNS_PY" || true)
if [[ -z "$RUNS_TERMINAL_LINE" ]]; then
    echo "[D7-C] FATAL: runs.py has no terminal_stages line; parser needs an update" >&2
    violations=$((violations + 1))
else
    RUNS_TERMINAL=$(printf '%s\n' "$RUNS_TERMINAL_LINE" | /usr/bin/grep -oE '"[a-z_]+"' | /usr/bin/tr -d '"' | /usr/bin/sort -u)
    if [[ "$RUNS_TERMINAL" != "$DISPATCHER_TERMINAL" ]]; then
        echo "[D7-C] runs.py terminal_stages drift" >&2
        echo "      dispatcher.sh terminal: $(printf '%s' "$DISPATCHER_TERMINAL" | tr '\n' ' ')" >&2
        echo "      runs.py terminal:       $(printf '%s' "$RUNS_TERMINAL" | tr '\n' ' ')" >&2
        violations=$((violations + 1))
    fi
fi

# --- D7-D: active ∩ terminal must be empty (no stage in both sets) ---
OVERLAP=$(/usr/bin/comm -12 <(echo "$DISPATCHER_ACTIVE") <(echo "$DISPATCHER_TERMINAL") || true)
if [[ -n "$OVERLAP" ]]; then
    echo "[D7-D] dispatcher.sh has stages in BOTH active and terminal sets:" >&2
    echo "      overlap: $OVERLAP" >&2
    violations=$((violations + 1))
fi

if (( violations > 0 )); then
    echo "" >&2
    echo "FAIL: $violations stage-set consistency violation(s)" >&2
    echo "      Canonical source is dispatcher.sh; align the others to match it." >&2
    exit 1
fi

echo "OK: stage-set definitions consistent across dispatcher.sh, update_phase_from_stages.sh, launcher.py, runs.py"
echo "    active   = $(printf '%s' "$DISPATCHER_ACTIVE" | tr '\n' ' ')"
echo "    terminal = $(printf '%s' "$DISPATCHER_TERMINAL" | tr '\n' ' ')"
exit 0
