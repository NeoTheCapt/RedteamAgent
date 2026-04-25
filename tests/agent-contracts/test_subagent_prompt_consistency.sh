#!/usr/bin/env bash
set -euo pipefail

# test_subagent_prompt_consistency.sh — D1/D2 CI consistency check.
#
# The 7 sub-agent prompts under agent/.opencode/prompts/agents/ duplicate
# two blocks verbatim that drift if hand-edited:
#
#   D1. SUBAGENT BOUNDARY: a 1-line guard rail that's identical across
#       all 7 prompts. Any divergence (typo, half-edit, missing) means
#       one subagent silently lacks the boundary rule.
#
#   D2. FINDING IDs: the 4-line "never hand-allocate" block. Format is
#       identical except for two substitutions:
#         - the subagent name (used in append_finding.sh argument)
#         - the 2-letter prefix (RE/SA/VA/EX/FZ/OS)
#       If a future edit forgets to update agent name OR prefix, findings
#       get appended under the wrong agent — observed pattern in 2026-04-25
#       audit.
#
# Exit 0 = pass, 1 = violation, 2 = harness error. Run from repo root.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROMPTS_DIR="$ROOT/agent/.opencode/prompts/agents"

if [[ ! -d "$PROMPTS_DIR" ]]; then
    echo "FATAL: prompts dir not found: $PROMPTS_DIR" >&2
    exit 2
fi

violations=0

# Map: subagent_name → expected finding-prefix (uppercase).
# Bash 3.2 (macOS default) lacks associative arrays — use a case lookup.
expected_prefix_for() {
    case "$1" in
        recon-specialist)       echo "RE" ;;
        source-analyzer)        echo "SA" ;;
        vulnerability-analyst)  echo "VA" ;;
        exploit-developer)      echo "EX" ;;
        fuzzer)                 echo "FZ" ;;
        osint-analyst)          echo "OS" ;;
        *)                      echo "" ;;
    esac
}

# Subagents that own a finding prefix (operator and report-writer do not).
SUBAGENTS_WITH_FINDINGS="recon-specialist source-analyzer vulnerability-analyst exploit-developer fuzzer osint-analyst"

# All subagents that must carry the SUBAGENT BOUNDARY block (includes report-writer).
SUBAGENTS_WITH_BOUNDARY="recon-specialist source-analyzer vulnerability-analyst exploit-developer fuzzer osint-analyst report-writer"

# --- D1: SUBAGENT BOUNDARY ---
# The canonical line. If any subagent deviates from this string, fail.
CANONICAL_BOUNDARY='SUBAGENT BOUNDARY: You are not the operator. Do NOT use `task` or `todowrite`. Do NOT dispatch other subagents, do NOT run `/engage` or `/resume`, and do NOT manage `cases.db`, `dispatcher.sh`, or queue-state helpers. Stay inside the assigned scope and return results directly to the operator.'

for agent in $SUBAGENTS_WITH_BOUNDARY; do
    file="$PROMPTS_DIR/$agent.txt"
    if [[ ! -f "$file" ]]; then
        echo "[D1] MISSING prompt file: $file" >&2
        violations=$((violations + 1))
        continue
    fi
    if ! /usr/bin/grep -qF "$CANONICAL_BOUNDARY" "$file"; then
        echo "[D1] $agent: SUBAGENT BOUNDARY block missing or drifted from canonical text" >&2
        echo "      file: $file" >&2
        actual="$(/usr/bin/grep -m1 'SUBAGENT BOUNDARY:' "$file" || echo '<no SUBAGENT BOUNDARY line>')"
        echo "      actual:" >&2
        echo "        $actual" >&2
        violations=$((violations + 1))
    fi
done

# --- D2: FINDING IDs ---
# Pattern check: must reference correct agent name + correct prefix.
for agent in $SUBAGENTS_WITH_FINDINGS; do
    file="$PROMPTS_DIR/$agent.txt"
    [[ ! -f "$file" ]] && continue  # already flagged by D1 if missing
    expected_prefix="$(expected_prefix_for "$agent")"

    # 1. append_finding.sh agent-name must match the file's own agent.
    if ! /usr/bin/grep -qE "append_finding\.sh \"\\\$DIR\" $agent " "$file"; then
        echo "[D2] $agent: append_finding.sh line missing or wrong agent-name argument" >&2
        echo "      file: $file" >&2
        actual="$(/usr/bin/grep -m1 "append_finding\.sh" "$file" || echo '<not found>')"
        echo "      actual: $actual" >&2
        violations=$((violations + 1))
    fi

    # 2. The next-FINDING line must use the correct prefix.
    if ! /usr/bin/grep -qE "FINDING-${expected_prefix}-NNN" "$file"; then
        echo "[D2] $agent: missing or wrong finding-prefix; expected FINDING-${expected_prefix}-NNN" >&2
        echo "      file: $file" >&2
        actual="$(/usr/bin/grep -m1 -oE 'FINDING-[A-Z]+-NNN' "$file" || echo '<not found>')"
        echo "      actual: $actual" >&2
        violations=$((violations + 1))
    fi

    # 3. agent's prompt must NOT reference another agent's prefix
    #    (catches copy-paste errors like "FZ" inside vulnerability-analyst).
    for other_agent in $SUBAGENTS_WITH_FINDINGS; do
        [[ "$other_agent" == "$agent" ]] && continue
        other_prefix="$(expected_prefix_for "$other_agent")"
        if /usr/bin/grep -qE "FINDING-${other_prefix}-NNN" "$file"; then
            echo "[D2] $agent: references another agent's finding prefix FINDING-${other_prefix}-NNN" >&2
            echo "      file: $file (probably copy-paste error)" >&2
            violations=$((violations + 1))
        fi
    done
done

if [[ $violations -gt 0 ]]; then
    echo "" >&2
    echo "FAIL: $violations consistency violation(s) across sub-agent prompts" >&2
    exit 1
fi

echo "OK: SUBAGENT BOUNDARY and FINDING IDs blocks consistent across all sub-agent prompts"
exit 0
