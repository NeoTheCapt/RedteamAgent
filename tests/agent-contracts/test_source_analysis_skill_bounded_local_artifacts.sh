#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_ROOT/agent/skills/source-analysis/SKILL.md"

check() {
  local needle="$1"
  grep -Fq "$needle" "$SKILL" || {
    echo "missing source-analysis guardrail: $needle" >&2
    exit 1
  }
}

check 'prefer the local files over re-fetching remote content'
check 'Do **not** dump or `read` entire large/minified bundles into context'
check 'Avoid the `file` utility in runtime containers'
check 'When matches explode because of minified code, narrow the regex and rerun instead of accepting giant output'
check 'Fetch `.map` only when there is an explicit source map reference or saved map artifact'

echo 'source-analysis skill guardrails present'
