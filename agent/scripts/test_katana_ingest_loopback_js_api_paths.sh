#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/scans"

cat > "$ENG_DIR/scope.json" <<'EOF'
{
  "target": "http://host.docker.internal:8000",
  "hostname": "host.docker.internal",
  "port": 8000,
  "scope": ["host.docker.internal", "*.host.docker.internal"],
  "status": "in_progress",
  "current_phase": "collect"
}
EOF

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat > "$ENG_DIR/scans/katana_output.jsonl" <<'EOF'
{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/user/authentication-details/","tag":"js","attribute":"regex","source":"http://127.0.0.1:8000/main.js"},"response":{"status_code":401,"headers":{"Content-Type":"application/json"}}}
{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/user/login","tag":"js","attribute":"regex","source":"http://127.0.0.1:8000/main.js"},"response":{"status_code":500,"headers":{"Content-Type":"application/json"}}}
{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/rest/ghost-route","tag":"js","attribute":"regex","source":"http://127.0.0.1:8000/main.js"},"response":{"status_code":404,"headers":{"Content-Type":"application/json"}}}
EOF

KATANA_INGEST_SKIP_START=1 \
KATANA_INGEST_ONESHOT=1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null

count_401="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/rest/user/authentication-details/' AND source = 'katana';")"
count_500="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/rest/user/login' AND source = 'katana';")"
count_404="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/rest/ghost-route';")"

if [[ "$count_401" != "1" ]]; then
  echo "FAIL: expected 401 auth details route to be ingested once, got $count_401" >&2
  exit 1
fi

if [[ "$count_500" != "1" ]]; then
  echo "FAIL: expected 500 login route to be ingested once, got $count_500" >&2
  exit 1
fi

if [[ "$count_404" != "0" ]]; then
  echo "FAIL: expected 404 regex-only route to stay filtered, got $count_404" >&2
  exit 1
fi

echo "PASS: katana ingest keeps loopback JS API paths for 401/500 and still filters 404 noise"
