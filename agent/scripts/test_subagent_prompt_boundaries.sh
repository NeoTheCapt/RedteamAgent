#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CFG="$REPO_ROOT/agent/.opencode/opencode.json"

if jq -e '.instructions[] | select(. == "skills/case-dispatching/SKILL.md")' "$CFG" >/dev/null; then
  echo "operator-only case-dispatching skill still loaded globally in $CFG" >&2
  exit 1
fi

for agent in recon-specialist source-analyzer vulnerability-analyst exploit-developer fuzzer osint-analyst report-writer; do
  prompt="$REPO_ROOT/agent/.opencode/prompts/agents/${agent}.txt"
  grep -Fq 'SUBAGENT BOUNDARY:' "$prompt" || {
    echo "missing subagent boundary guard in $prompt" >&2
    exit 1
  }
  grep -Fq 'Do NOT use `task` or `todowrite`.' "$prompt" || {
    echo "missing task/todowrite recursion guard in $prompt" >&2
    exit 1
  }
  grep -Fq 'Do NOT dispatch other subagents' "$prompt" || {
    echo "missing no-subagent-dispatch guard in $prompt" >&2
    exit 1
  }
done

echo "PASS: subagent prompts enforce no-recursion boundaries and global instructions stay operator-safe"
