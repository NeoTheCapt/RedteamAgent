#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "https://www.okx.com",
  "hostname": "www.okx.com",
  "port": 443,
  "scope": ["www.okx.com", "*.okx.com"],
  "status": "in_progress",
  "current_phase": "collect"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat > "$ENG_DIR/scans/katana_output.jsonl" <<'EOF'
{"request":{"method":"GET","endpoint":"https://www.okx.com/en-sg","tag":"navigation","attribute":"visit","source":"https://www.okx.com/en-sg"},"response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}
{"request":{"method":"GET","endpoint":"https://www.okx.com/cdn/assets/okfe/okx-nav/common/'.concat(i,'","tag":"img","attribute":"src","source":"https://www.okx.com/cdn/assets/okfe/okx-nav/common/trade-common-box.bf8ea570.js"}}
EOF

KATANA_INGEST_SKIP_START=1 \
KATANA_INGEST_ONESHOT=1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null

good_count="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.okx.com/en-sg' AND source = 'katana';")"

if [[ "$good_count" != "1" ]]; then
  echo "FAIL: expected valid OKX page row to be ingested once, got $good_count" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

if rg -n "concat\(i" "$ENG_DIR/scans/katana_output.jsonl" >/dev/null 2>&1; then
  echo "FAIL: expected malformed concat path to be removed from public katana_output.jsonl" >&2
  cat "$ENG_DIR/scans/katana_output.jsonl" >&2
  exit 1
fi

if sqlite3 "$ENG_DIR/cases.db" "SELECT 1 FROM cases WHERE url LIKE '%concat(i%' LIMIT 1;" | grep -q 1; then
  echo "FAIL: expected malformed concat path to stay out of cases.db" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana ingest filters malformed concat paths from both cases.db and public artifact"
