#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! rg -q --fixed-strings "$pattern" "$file"; then
    echo "[FAIL] Missing pattern in $file: $pattern" >&2
    return 1
  fi
}

OP_INSTR="$REPO_ROOT/agent/.opencode/instructions/INSTRUCTIONS.md"
OP_PROMPT="$REPO_ROOT/agent/.opencode/prompts/agents/operator.txt"
ENGAGE_CMD="$REPO_ROOT/agent/.opencode/commands/engage.md"

assert_contains "$OP_INSTR" "OpenCode's right-side task/progress UI is driven by the built-in todo tools"
assert_contains "$OP_INSTR" 'Initialize a todo list immediately after `/engage` setup completes'
assert_contains "$OP_PROMPT" "OpenCode's native right-side progress UI comes from the built-in todo tools"
assert_contains "$OP_PROMPT" "todowrite"
assert_contains "$OP_PROMPT" "todoread"
assert_contains "$ENGAGE_CMD" 'Before Phase 1 begins, initialize OpenCode'"'"'s native progress UI with `todowrite`'
assert_contains "$ENGAGE_CMD" 'Do not rely on `/status` alone for progress UI.'

echo "[OK] OpenCode progress contracts are present"
