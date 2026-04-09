#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPERATOR_CORE="$REPO_ROOT/agent/operator-core.md"
ENGAGE_CMD="$REPO_ROOT/agent/.opencode/commands/engage.md"

for file in "$OPERATOR_CORE" "$ENGAGE_CMD"; do
  grep -Fq './scripts/fetch_batch_to_file.sh "$DIR/cases.db" <type> <limit> <agent> "$BATCH_FILE"' "$file" || {
    echo "missing fetch_batch_to_file helper guidance in $file" >&2
    exit 1
  }
  grep -Fq 'NEVER `cat "$BATCH_FILE"`' "$file" || {
    echo "missing no-raw-batch guard in $file" >&2
    exit 1
  }
  grep -Fq 'Treat the non-empty fetch and matching `task(...)` call as one atomic consume-test step' "$file" || {
    echo "missing atomic fetch+dispatch guidance in $file" >&2
    exit 1
  }
  grep -Fq 'MUST NOT also prefetch the next non-empty batch unless that SAME assistant turn will immediately launch the matching' "$file" || {
    echo "missing no-prefetch-without-dispatch guard in $file" >&2
    exit 1
  }
  grep -Fq 'NEVER combine outcome recording (`done`, `error`, `requeue`, `append_*`, queue stats, scope/findings/log updates) and `fetch_batch_to_file.sh` in the same bash/tool call' "$file" || {
    echo "missing no record+fetch same tool call guard in $file" >&2
    exit 1
  }
  grep -Fq 'tool result ends with `BATCH_COUNT > 0`, that assistant turn is not complete until the matching `task(...)` call has been issued' "$file" || {
    echo "missing BATCH_COUNT completion guard in $file" >&2
    exit 1
  }
done

echo "PASS: consume-test prompt guards present in operator-core and /engage"
