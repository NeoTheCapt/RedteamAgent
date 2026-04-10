#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans" "$ENG_DIR/pids"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "https://www.example.com",
  "hostname": "www.example.com",
  "port": 443,
  "scope": ["www.example.com", "*.example.com"],
  "status": "in_progress",
  "current_phase": "recon"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat > "$ENG_DIR/scans/katana_output.jsonl" <<'EOF'
{"request":{"method":"GET","endpoint":"https://www.example.com/cdn/assets/okfe/example-nav/vendor/index.c83d5de1.js","tag":"script","attribute":"src","source":"https://www.example.com/en-sg"},"error":"hybrid: response is nil"}
{"request":{"method":"GET","endpoint":"https://www.example.com/priapi/v1/dx/market/v2/watchlist/token/group/create","tag":"js","attribute":"regex","source":"https://www.example.com/cdn/assets/okfe/example-nav/vendor/index.c83d5de1.js"},"error":"hybrid: response is nil"}
EOF

KATANA_INGEST_SKIP_START=1 \
KATANA_INGEST_ONESHOT=1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" > "$ENG_DIR/scans/katana_ingest.log" 2>&1

count_script="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/cdn/assets/okfe/example-nav/vendor/index.c83d5de1.js' AND source = 'katana';")"
count_api_as_katana="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/priapi/v1/dx/market/v2/watchlist/token/group/create' AND source = 'katana';")"
count_api_as_xhr="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'https://www.example.com/priapi/v1/dx/market/v2/watchlist/token/group/create' AND source = 'katana-xhr';")"

if [[ "$count_script" != "1" ]]; then
  echo "FAIL: expected recoverable script-src discovery to stay katana, got $count_script" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

if [[ "$count_api_as_katana" != "1" ]]; then
  echo "FAIL: expected recoverable js-regex API discovery to remain katana until a real XHR is captured, got $count_api_as_katana" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

if [[ "$count_api_as_xhr" != "0" ]]; then
  echo "FAIL: expected recoverable js-regex API discovery not to masquerade as katana-xhr, got $count_api_as_xhr" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: recoverable js-regex hybrid discoveries stay katana and no longer inflate katana-xhr source counts"
