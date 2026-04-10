#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPERATOR_CORE="$REPO_ROOT/agent/operator-core.md"
ENGAGE_CMD="$REPO_ROOT/agent/.opencode/commands/engage.md"
RESUME_CMD="$REPO_ROOT/agent/.opencode/commands/resume.md"

for file in "$OPERATOR_CORE" "$ENGAGE_CMD"; do
  grep -Fq 'coverage-expanding source batches remain pending' "$file" || {
    echo "missing coverage-expanding source guidance in $file" >&2
    exit 1
  }
  grep -Fq 'generic low-yield `page`, `stylesheet`, or `data` backlog' "$file" || {
    echo "missing low-yield backlog starvation guard in $file" >&2
    exit 1
  }
  grep -Fq 'bundle-derived routes/surfaces can materialize into follow-up cases' "$file" || {
    echo "missing benchmark/source-coverage preference guidance in $file" >&2
    exit 1
  }
done

grep -Fq 'coverage-expanding `api-spec|javascript|unknown` rows remain pending' "$RESUME_CMD" || {
  echo "missing source-analyzer resume priority guidance" >&2
  exit 1
}
grep -Fq 'generic low-yield `page|stylesheet|data` backlog' "$RESUME_CMD" || {
  echo "missing low-yield resume starvation guard" >&2
  exit 1
}

python3 - "$RESUME_CMD" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding='utf-8')
needles = [
    "'api-spec vulnerability-analyst'",
    "'javascript source-analyzer'",
    "'unknown source-analyzer'",
    "'api vulnerability-analyst'",
    "'page source-analyzer'",
]
pos = [text.find(n) for n in needles]
if any(p == -1 for p in pos):
    raise SystemExit('missing one or more resume batch-order entries')
if not (pos[0] < pos[1] < pos[2] < pos[3] < pos[4]):
    raise SystemExit('resume batch order does not prioritize coverage-expanding source batches before API and generic page backlog after API')
PY

echo "PASS: consume-test prompts prioritize unresolved source coverage before more API churn"
