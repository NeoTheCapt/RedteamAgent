#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGAGE_MD="$ROOT/agent/.opencode/commands/engage.md"
OPERATOR_TXT="$ROOT/agent/.opencode/prompts/agents/operator.txt"
TEST_SCRIPT="$ROOT/tools/opencode-debug/test-engage.sh"
OPENCODE_JSON="$ROOT/agent/.opencode/opencode.json"
PLUGIN_TS="$ROOT/agent/.opencode/plugins/engagement-hooks.ts"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

pass() {
  echo "PASS: $1"
}

# Auto mode must not require manual approval.
if grep -q "Wait for user approval before sending traffic" "$ENGAGE_MD"; then
  fail "auto mode contract is contradicted by unconditional approval wait"
fi
pass "auto mode does not contain unconditional approval wait"

if grep -q "PRESENT AND WAIT" "$OPERATOR_TXT"; then
  fail "operator core loop still forces wait semantics in autonomous mode"
fi
pass "operator core loop allows autonomous execution without waiting"

# Long-running background producers must detach their stdio.
if grep -Eq 'katana_ingest\.sh "\$DIR" &' "$ENGAGE_MD"; then
  fail "background katana_ingest starts without stdout/stderr redirection"
fi
pass "background producer startup detaches stdio"

if ! grep -q "katana_ingest_pid=\$!" "$ENGAGE_MD"; then
  fail "engage command is missing explicit safe katana PID capture guidance"
fi
pass "engage command documents safe katana PID capture"

if grep -q "run the /engage command against" "$TEST_SCRIPT"; then
  fail "test-engage.sh uses natural language prompt instead of direct slash command"
fi
pass "test-engage.sh uses direct slash command invocation"

if grep -q '"\.\/\.opencode\/plugins"' "$OPENCODE_JSON"; then
  fail "opencode plugin path is rooted twice and resolves to .opencode/.opencode/plugins"
fi
pass "opencode plugin path is relative to the config directory"

if grep -qE '\$\`.*(>>|2>/dev/null|\*/scope\.json).*\`' "$PLUGIN_TS"; then
  fail "plugin uses shell redirection or globbing inside \$ template commands"
fi
pass "plugin avoids shell-only syntax inside command templates"

if ! grep -qE 'Before Step 2 completes, do NOT read .*scope\.json.*log\.md.*findings\.md' "$ENGAGE_MD"; then
  fail "engage command is missing an explicit pre-init no-read guard"
fi
pass "engage command forbids reading state files before initialization"

if ! grep -qE 'Do NOT look for `engage\.md` under `scripts/`' "$ENGAGE_MD"; then
  fail "engage command is missing an explicit wrong-path guard for scripts/engage.md"
fi
pass "engage command forbids wrong-path engage.md lookups"

if ! grep -q "core loop starts only after /engage initialization completes" "$OPERATOR_TXT"; then
  fail "operator prompt does not explicitly delay the core loop until init completes"
fi
pass "operator prompt delays the core loop until initialization completes"

if ! grep -q "Reuse existing evidence before issuing new probes\." "$OPERATOR_TXT"; then
  fail "operator prompt is missing bounded surface follow-up guidance"
fi
pass "operator prompt requires reusing existing evidence before new probes"

if ! grep -q -- '--connect-timeout 5' "$OPERATOR_TXT" || ! grep -q -- '--max-time 20' "$OPERATOR_TXT"; then
  fail "operator prompt is missing explicit timeout bounds for ad-hoc run_tool curl validation"
fi
pass "operator prompt requires explicit curl timeout bounds during surface follow-up"

if ! grep -q 'Never launch long multi-endpoint bundles, unbounded loops, or background probes during surface-coverage follow-up\.' "$OPERATOR_TXT"; then
  fail "operator prompt still allows unbounded surface follow-up probing"
fi
pass "operator prompt forbids unbounded surface follow-up probing"

if ! grep -q 'do not stop after only writing a log entry like `Credential validation dispatch`' "$OPERATOR_TXT"; then
  fail "operator prompt does not forbid log-only credential validation stalls"
fi
pass "operator prompt forbids log-only credential validation stalls"

if ! grep -q 'If credentials are discovered during consume-test, write them to auth.json and in that SAME turn dispatch a bounded exploit-developer auth-validation task' "$ENGAGE_MD"; then
  fail "engage command is missing same-turn credential validation guidance"
fi
pass "engage command requires same-turn credential validation"

if ! grep -q 'authorized lab mirrors resolved inside the harness' "$OPERATOR_TXT"; then
  fail "operator prompt is missing explicit branded-target lab-mirror authorization guidance"
fi
pass "operator prompt treats branded orchestrator targets as authorized lab mirrors"

if ! grep -q 'authorized lab mirrors/local simulations' "$ROOT/agent/.opencode/commands/autoengage.md"; then
  fail "autoengage command is missing branded-target authorization guidance"
fi
pass "autoengage command documents branded-target authorization handling"

if ! grep -q 'authorized lab mirror/local simulation' "$ENGAGE_MD"; then
  fail "engage command is missing branded-target authorization guidance"
fi
pass "engage command treats public-looking orchestrated targets as in-scope lab mirrors"
