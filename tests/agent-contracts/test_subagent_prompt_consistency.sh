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
#   D5. CASE BATCH framing: the canonical sentence
#         "the operator framing includes BATCH_FILE / BATCH_IDS"
#       must appear in every case-batch sub-agent's prompt so the agent
#       knows where to read its inputs. fetch_batch_to_file.sh emits 9
#       BATCH_* keys and FILE+IDS are how the agent locates its case set.
#       Drift observed in 2026-04-25 audit: exploit-developer + fuzzer had
#       the canonical sentence; source-analyzer + vulnerability-analyst
#       had only the bare "Every input case ID" requirement, leaving the
#       framing-key contract implicit.
#
#   D6. EXPLOIT CTF solved-state: exploit-developer must carry explicit guidance
#       to perform a bounded canonical challenge-triggering action after proving a
#       lab/CTF vulnerability. A 2026-04-25 local Juice Shop run wrote 20 findings
#       but scored 0/111 because confirmed exploits were treated as report-only
#       evidence instead of app solved-state triggers.
#
#   D7. AUTH ARTIFACT CONSUMPTION: exploit-developer must also say that recovered
#       auth artifacts (admin session/JWT, reset token, security answers, successful
#       registration) are not exhausted until the agent consumes them on one concrete
#       privileged route/control, and must not end with "no multi-step attack path
#       assessed" while that follow-up is still outstanding.
#
#   D8. EXACT ROUTE FOLLOW-UP DEDUPE: operator + source-analyzer must agree that
#       once an exact browser-flow follow-up for a concrete route is already preserved,
#       later sibling carriers collapse into that same route should be retired instead
#       of requeueing another duplicate live-route task. Drift here caused repeated
#       privacy-security requeues in the 2026-04-25 recall audit.
#
#   D9. FIRST LIVE-ROUTE OWNERSHIP: once source-analysis has already proved a
#       concrete fragment route exists and named the first browser_flow.py step,
#       that page case is exhausted for source-analysis. The operator must hand the
#       first live route execution to exploit-developer (or equivalent live-route
#       owner) instead of sending the same page case back through source-analyzer.
#       Drift here caused exact route cases to loop in source-analysis even after
#       route-capture had already proven the page existed.
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

# --- D5: CASE BATCH framing ---
# Every case-batch sub-agent must point to the operator framing that wraps the
# dispatch — specifically the BATCH_FILE (path to the JSON batch on disk) and
# BATCH_IDS (comma-separated case IDs) keys emitted by fetch_batch_to_file.sh.
# We check for the canonical inline substring `BATCH_FILE / BATCH_IDS` on any
# single line; the surrounding sentence ("the operator framing includes ...")
# can wrap freely without breaking the check. This applies to source-analyzer
# / vulnerability-analyst / exploit-developer / fuzzer — the four agents that
# consume `fetch-by-stage` batches. recon-specialist, osint-analyst, and
# report-writer don't take case batches.
CANONICAL_BATCH_FRAMING='BATCH_FILE / BATCH_IDS'

SUBAGENTS_WITH_CASE_BATCHES="source-analyzer vulnerability-analyst exploit-developer fuzzer"

for agent in $SUBAGENTS_WITH_CASE_BATCHES; do
    file="$PROMPTS_DIR/$agent.txt"
    [[ ! -f "$file" ]] && continue  # already flagged by D1
    if ! /usr/bin/grep -qF "$CANONICAL_BATCH_FRAMING" "$file"; then
        echo "[D5] $agent: missing canonical CASE BATCH framing token" >&2
        echo "      file: $file" >&2
        echo "      expected substring: $CANONICAL_BATCH_FRAMING" >&2
        violations=$((violations + 1))
    fi
done

# --- D6/D7: EXPLOIT CTF SOLVED-STATE + AUTH ARTIFACT CONSUMPTION ---
# Confirmed exploit evidence should also trigger the lab app's own solved-state when
# an exact canonical action is already known. Recovered auth artifacts must be consumed
# on one concrete route/control before the branch can be closed.
EXPLOIT_PROMPT="$PROMPTS_DIR/exploit-developer.txt"
for required in \
    'canonical challenge-triggering action' \
    'Juice Shop-style recall scoring' \
    "app's challenge state" \
    'admin JWT/session, password-reset token, recovered security answers, registration success' \
    'no multi-step attack path assessed' \
    'STAGE=vuln_confirmed'; do
    if ! /usr/bin/grep -qF "$required" "$EXPLOIT_PROMPT"; then
        echo "[D6/D7] exploit-developer: missing solved-state/auth-consumption guidance token: $required" >&2
        echo "      file: $EXPLOIT_PROMPT" >&2
        violations=$((violations + 1))
    fi
done

# --- D8/D9: EXACT ROUTE FOLLOW-UP DEDUPE + FIRST LIVE-ROUTE OWNERSHIP ---
OPERATOR_PROMPT="$PROMPTS_DIR/operator.txt"
SOURCE_PROMPT="$PROMPTS_DIR/source-analyzer.txt"
SKILL_FILE="$ROOT/agent/skills/source-analysis/SKILL.md"

for required in \
    'dispatch one bounded live route execution for that exact route before fetching another same-family surface/page batch' \
    'treat later sibling carriers as duplicates to retire' \
    'Hand that exact route to exploit-developer as the live-route execution owner next'; do
    if ! /usr/bin/grep -qF "$required" "$OPERATOR_PROMPT"; then
        echo "[D8/D9] operator: missing exact-route/live-route guidance token: $required" >&2
        echo "      file: $OPERATOR_PROMPT" >&2
        violations=$((violations + 1))
    fi
done

for required in \
    'do not keep multiple sibling carriers pending for the same exact route' \
    'Requeue only one representative queue row per exact route/workflow until that live follow-up runs' \
    'The first bounded browser-flow pass belongs to exploit-developer or another live-route execution owner, not another source-analysis revisit' \
    'return `DONE STAGE=clean`, not `REQUEUE`, unless new source artifacts arrived that materially change the route evidence'; do
    if ! /usr/bin/grep -qF "$required" "$SOURCE_PROMPT"; then
        echo "[D8/D9] source-analyzer: missing exact-route/live-route guidance token: $required" >&2
        echo "      file: $SOURCE_PROMPT" >&2
        violations=$((violations + 1))
    fi
done

for required in \
    'Do **not** keep sending the same page case back through source-analysis just to wait for the first live route execution' \
    'That first bounded browser-flow pass belongs to exploit-developer or another live-route execution owner'; do
    if ! /usr/bin/grep -qF "$required" "$SKILL_FILE"; then
        echo "[D8/D9] source-analysis skill: missing exact-route/live-route guidance token: $required" >&2
        echo "      file: $SKILL_FILE" >&2
        violations=$((violations + 1))
    fi
done

if [[ $violations -gt 0 ]]; then
    echo "" >&2
    echo "FAIL: $violations consistency violation(s) across sub-agent prompts" >&2
    exit 1
fi

echo "OK: SUBAGENT BOUNDARY, FINDING IDs, CASE BATCH framing, and exact-route/live-route guidance consistent across prompts"
exit 0
