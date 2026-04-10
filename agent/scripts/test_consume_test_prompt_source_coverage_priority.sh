#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPERATOR_CORE="$REPO_ROOT/agent/operator-core.md"
ENGAGE_CMD="$REPO_ROOT/agent/.opencode/commands/engage.md"
RESUME_CMD="$REPO_ROOT/agent/.opencode/commands/resume.md"

for file in "$OPERATOR_CORE" "$ENGAGE_CMD"; do
  grep -Fq 'do NOT keep chaining vulnerability-analyst batches indefinitely' "$file" || {
    echo "missing non-API starvation guard in $file" >&2
    exit 1
  }
  grep -Fq 'bundle-derived routes/surfaces can materialize into follow-up cases' "$file" || {
    echo "missing benchmark/source-coverage preference guidance in $file" >&2
    exit 1
  }
done

grep -Fq 'attempt a `source-analyzer` fetch before taking another API-family batch' "$RESUME_CMD" || {
  echo "missing source-analyzer resume priority guidance" >&2
  exit 1
}

python3 - "$RESUME_CMD" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding='utf-8')
needles = [
    "'api-spec vulnerability-analyst'",
    "'page source-analyzer'",
    "'javascript source-analyzer'",
    "'api vulnerability-analyst'",
]
pos = [text.find(n) for n in needles]
if any(p == -1 for p in pos):
    raise SystemExit('missing one or more resume batch-order entries')
if not (pos[0] < pos[1] < pos[2] < pos[3]):
    raise SystemExit('resume batch order does not prioritize source-analyzer batches ahead of general API batches')
PY

echo "PASS: consume-test prompts prioritize unresolved source coverage before more API churn"
