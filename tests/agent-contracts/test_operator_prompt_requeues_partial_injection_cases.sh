#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROMPT="$REPO_ROOT/agent/.opencode/prompts/agents/operator.txt"

grep -Fq 'if subagent output includes `REQUEUE_CANDIDATE` or clearly says an endpoint still has an untested higher-risk family, do NOT mark that case exhausted' "$PROMPT" || {
  echo 'missing operator guidance to requeue partial high-risk cases' >&2
  exit 1
}

echo 'PASS: operator prompt preserves partial-case requeue handling'
