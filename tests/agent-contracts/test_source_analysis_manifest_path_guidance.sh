#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL_FILE="$REPO_ROOT/agent/skills/source-analysis/SKILL.md"
PROMPT_FILE="$REPO_ROOT/agent/.opencode/prompts/agents/source-analyzer.txt"

for file in "$SKILL_FILE" "$PROMPT_FILE"; do
  grep -Fqi 'preserve' "$file" || {
    echo "missing preserve guidance in $file" >&2
    exit 1
  }
  grep -Eq 'NoSuchKey|AccessDenied' "$file" || {
    echo "missing placeholder object-storage guidance in $file" >&2
    exit 1
  }
done

grep -Fq 'Do **not** prepend nearby version directories' "$SKILL_FILE" || {
  echo "missing manifest path preservation rule in $SKILL_FILE" >&2
  exit 1
}

grep -Fqi 'do NOT prepend guessed version directories or CDN subpaths' "$PROMPT_FILE" || {
  echo "missing manifest path preservation rule in $PROMPT_FILE" >&2
  exit 1
}

echo "PASS: source-analysis guidance preserves manifest asset paths and rejects object-storage placeholders"
