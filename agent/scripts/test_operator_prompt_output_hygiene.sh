#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPERATOR_CORE="$REPO_ROOT/agent/operator-core.md"
RENDER_SCRIPT="$REPO_ROOT/agent/scripts/render-operator-prompts.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for needle in \
  "default to a literal heredoc (\`<<'EOF'\`) unless you intentionally need shell interpolation" \
  'Surface targets must stay concrete and requestable after normalization' \
  'do NOT emit unresolved path placeholders such as `<id>`, `{id}`, `FUZZ`, `PARAM`, or `{{token}}` into `surfaces.jsonl`'
do
  grep -Fq "$needle" "$OPERATOR_CORE" || {
    echo "missing operator-core guard: $needle" >&2
    exit 1
  }
done

bash "$RENDER_SCRIPT" repo "$TMP_DIR"

grep -Fq "For literal/static Markdown, JSON, or script bodies, use a single-quoted delimiter (\`<<'EOF'\`)" "$TMP_DIR/CLAUDE.md" || {
  echo "missing safe heredoc guidance in rendered CLAUDE.md" >&2
  exit 1
}
if grep -Fq "HEREDOC: Use unquoted delimiter (\`<< EOF\`), NOT single-quoted (\`<< 'EOF'\`)." "$TMP_DIR/CLAUDE.md"; then
  echo "stale unsafe heredoc guidance still rendered in CLAUDE.md" >&2
  exit 1
fi

for file in "$TMP_DIR/CLAUDE.md" "$TMP_DIR/AGENTS.md"; do
  grep -Fq "default to a literal heredoc (\`<<'EOF'\`) unless you intentionally need shell interpolation" "$file" || {
    echo "missing operator-core literal-heredoc guard in $file" >&2
    exit 1
  }
  grep -Fq 'Surface targets must stay concrete and requestable after normalization' "$file" || {
    echo "missing concrete surface guidance in $file" >&2
    exit 1
  }
done

echo "PASS: operator prompt render emits safe heredoc and concrete-surface guidance"
