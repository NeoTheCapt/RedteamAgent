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
done

echo "PASS: consume-test prompt guards present in operator-core and /engage"
