#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENGAGE_MD="$ROOT/agent/.opencode/commands/engage.md"
OPERATOR_TXT="$ROOT/agent/.opencode/prompts/agents/operator.txt"
REPORT_MD="$ROOT/agent/.opencode/commands/report.md"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if ! grep -q './scripts/check_katana_usage.sh "$ENG_DIR"' "$REPORT_MD"; then
  fail "report flow does not block raw katana usage"
fi

if ! grep -q './scripts/check_collection_health.sh "$ENG_DIR"' "$REPORT_MD"; then
  fail "report flow does not validate collection health"
fi

if ! grep -q 'Never launch `katana` directly' "$OPERATOR_TXT"; then
  fail "operator prompt does not explicitly ban raw katana launches"
fi

if ! grep -q 'Only `./scripts/katana_ingest.sh` or `start_katana` may start crawling' "$ENGAGE_MD"; then
  fail "engage command does not restrict katana startup to the supported wrappers"
fi

echo "katana workflow contracts: ok"
