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
{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/.well-known/csaf/provider-metadata.json","tag":"file","attribute":"src","source":"http://127.0.0.1:8000/.well-known/csaf/"},"response":{"status_code":200,"headers":{"Content-Type":"application/json"}}}
{"request":{"method":"GET","endpoint":"http://127.0.0.1:8000/.well-known/csaf/3000/.well-known/csaf/provider-metadata.json","tag":"file","attribute":"src","source":"http://127.0.0.1:8000/.well-known/csaf/provider-metadata.json"},"error":"Get \"http://127.0.0.1:8000/.well-known/csaf/3000/.well-known/csaf/provider-metadata.json\": dial tcp 127.0.0.1:8000: connect: connection refused"}
EOF

KATANA_INGEST_SKIP_START=1 \
KATANA_INGEST_ONESHOT=1 \
"$ROOT/agent/scripts/katana_ingest.sh" "$ENG_DIR" >/dev/null

good_count="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/.well-known/csaf/provider-metadata.json' AND source = 'katana';")"

if [[ "$good_count" != "1" ]]; then
  echo "FAIL: expected valid loopback CSAF row to be ingested once, got $good_count" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

if rg -n '/\.well-known/csaf/3000/\.well-known/csaf/' "$ENG_DIR/scans/katana_output.jsonl" >/dev/null 2>&1; then
  echo "FAIL: expected malformed loopback rewrite row to be removed from public katana_output.jsonl" >&2
  cat "$ENG_DIR/scans/katana_output.jsonl" >&2
  exit 1
fi

if sqlite3 "$ENG_DIR/cases.db" "SELECT 1 FROM cases WHERE url LIKE '%/.well-known/csaf/3000/.well-known/csaf/%' LIMIT 1;" | grep -q 1; then
  echo "FAIL: expected malformed loopback rewrite row to stay out of cases.db" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT source, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: katana ingest filters malformed loopback rewrite rows from both cases.db and public artifact"
