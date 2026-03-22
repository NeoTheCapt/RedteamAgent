#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SOURCE_DIR="$REPO_ROOT/agent"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

"$SOURCE_DIR/scripts/render-operator-prompts.sh" repo "$TMP_DIR"

compare_file() {
  local expected="$1" actual="$2"
  if ! diff -u "$expected" "$actual"; then
    echo ""
    echo "[FAIL] Operator prompt drift detected: $actual"
    return 1
  fi
}

compare_file "$TMP_DIR/CLAUDE.md" "$SOURCE_DIR/CLAUDE.md"
compare_file "$TMP_DIR/AGENTS.md" "$SOURCE_DIR/AGENTS.md"
compare_file "$TMP_DIR/.claude/agents/operator.md" "$SOURCE_DIR/.claude/agents/operator.md"
compare_file "$TMP_DIR/.codex/agents/operator.toml" "$SOURCE_DIR/.codex/agents/operator.toml"

echo "[OK] Operator prompts are in sync with operator-core.md"
