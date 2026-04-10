#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

"$REPO_ROOT/agent/scripts/render-operator-prompts.sh" repo "$TMP_DIR"

compare_file() {
  local repo_file="$1"
  local rendered_file="$2"
  if ! diff -u "$repo_file" "$rendered_file" >/dev/null; then
    echo "rendered operator prompt drift detected: $repo_file != $rendered_file" >&2
    diff -u "$repo_file" "$rendered_file" >&2 || true
    exit 1
  fi
}

compare_file "$REPO_ROOT/agent/CLAUDE.md" "$TMP_DIR/CLAUDE.md"
compare_file "$REPO_ROOT/agent/AGENTS.md" "$TMP_DIR/AGENTS.md"
compare_file "$REPO_ROOT/agent/.opencode/prompts/agents/operator.txt" "$TMP_DIR/.opencode/prompts/agents/operator.txt"
compare_file "$REPO_ROOT/agent/.claude/agents/operator.md" "$TMP_DIR/.claude/agents/operator.md"
compare_file "$REPO_ROOT/agent/.codex/agents/operator.toml" "$TMP_DIR/.codex/agents/operator.toml"

echo "PASS: rendered operator prompt artifacts are in sync with operator-core.md"
