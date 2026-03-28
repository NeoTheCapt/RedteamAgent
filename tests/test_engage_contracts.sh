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
