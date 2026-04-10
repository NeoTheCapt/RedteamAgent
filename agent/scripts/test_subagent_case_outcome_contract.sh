#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VA_PROMPT="$REPO_ROOT/agent/.opencode/prompts/agents/vulnerability-analyst.txt"
SA_PROMPT="$REPO_ROOT/agent/.opencode/prompts/agents/source-analyzer.txt"

for file in "$VA_PROMPT" "$SA_PROMPT"; do
  grep -Fq 'Your final handoff MUST end with a literal `### Case Outcomes` section.' "$file" || {
    echo "missing mandatory ### Case Outcomes footer in $file" >&2
    exit 1
  }
  grep -Fq 'Every input case ID must' "$file" || {
    echo "missing every-case accountability rule in $file" >&2
    exit 1
  }
  grep -Fq 'After you emit `### Case Outcomes`, stop immediately and return that handoff to the operator.' "$file" || {
    echo "missing immediate-return guard after case outcomes in $file" >&2
    exit 1
  }
  grep -Fq 'Do not read more files' "$file" || {
    echo "missing no-extra-work-after-outcomes guard in $file" >&2
    exit 1
  }
  grep -Fq 'DONE <id>' "$file" || {
    echo "missing DONE outcome format in $file" >&2
    exit 1
  }
  grep -Fq 'REQUEUE <id>' "$file" || {
    echo "missing REQUEUE outcome format in $file" >&2
    exit 1
  }
  grep -Fq 'ERROR <id>' "$file" || {
    echo "missing ERROR outcome format in $file" >&2
    exit 1
  }
done

echo 'PASS: consume-test subagent prompts require literal per-case outcome handoffs'
