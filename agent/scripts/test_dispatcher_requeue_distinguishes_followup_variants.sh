#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat <<'EOF' | "$ROOT/agent/scripts/dispatcher.sh" "$ENG_DIR/cases.db" requeue >/dev/null
{"method":"POST","url":"http://host.docker.internal:8000/rest/products/search","url_path":"/rest/products/search","type":"api","source":"vulnerability-analyst","body_params":{"q":"abc","_followup":"baseline"}}
{"method":"POST","url":"http://host.docker.internal:8000/rest/products/search","url_path":"/rest/products/search","type":"api","source":"vulnerability-analyst","body_params":{"q":"abc","_followup":"quote-breakout"}}
EOF

count="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(*) FROM cases WHERE method='POST' AND url_path='/rest/products/search';")"
if [[ "$count" != "2" ]]; then
  echo "FAIL: expected two follow-up variants to coexist, got count=$count" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT id, method, url_path, body_params, params_key_sig, status FROM cases ORDER BY id;" >&2
  exit 1
fi

unique_sigs="$(sqlite3 "$ENG_DIR/cases.db" "SELECT COUNT(DISTINCT params_key_sig) FROM cases WHERE method='POST' AND url_path='/rest/products/search';")"
if [[ "$unique_sigs" != "2" ]]; then
  echo "FAIL: expected distinct params_key_sig values for follow-up variants, got $unique_sigs" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT id, body_params, params_key_sig FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: dispatcher requeue keeps follow-up variants with underscore control markers distinct"
