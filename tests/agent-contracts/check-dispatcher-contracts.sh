#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agent"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DB="$TMP_DIR/cases.db"
sqlite3 "$DB" < "$AGENT_DIR/scripts/schema.sql" >/dev/null

cat <<'EOF' | bash "$AGENT_DIR/scripts/dispatcher.sh" "$DB" requeue >/dev/null
{"method":"POST","url":"https://app.example.com/api/users?id=1","url_path":"/api/users","query_params":"{\"id\":\"1\"}","body_params":"{\"name\":\"alice\"}","path_params":"{\"seg_2\":\"users\"}","cookie_params":"{\"session\":\"abc\"}","headers":"{\"content-type\":\"application/json\"}","body":"{\"name\":\"alice\"}","content_type":"application/json","content_length":16,"response_status":201,"response_headers":"{\"location\":\"/api/users/123\"}","response_size":42,"response_snippet":"{\"id\":123}","type":"api","source":"source-analyzer","params_key_sig":"abc123"}
EOF

row_json="$(sqlite3 -json "$DB" "SELECT method, url, url_path, query_params, body_params, path_params, cookie_params, headers, body, content_type, content_length, response_status, response_headers, response_size, response_snippet, type, source, status, params_key_sig, assigned_agent, consumed_at FROM cases LIMIT 1;")"

python3 - "$row_json" <<'PY'
import json
import sys

rows = json.loads(sys.argv[1])
if len(rows) != 1:
    raise SystemExit("[FAIL] expected one requeued case row")

row = rows[0]
expected = {
    "method": "POST",
    "url": "https://app.example.com/api/users?id=1",
    "url_path": "/api/users",
    "query_params": '{"id":"1"}',
    "body_params": '{"name":"alice"}',
    "path_params": '{"seg_2":"users"}',
    "cookie_params": '{"session":"abc"}',
    "headers": '{"content-type":"application/json"}',
    "body": '{"name":"alice"}',
    "content_type": "application/json",
    "content_length": 16,
    "response_status": 201,
    "response_headers": '{"location":"/api/users/123"}',
    "response_size": 42,
    "response_snippet": '{"id":123}',
    "type": "api",
    "source": "source-analyzer",
    "status": "pending",
    "params_key_sig": "abc123",
    "assigned_agent": None,
    "consumed_at": None,
}

for key, value in expected.items():
    if row.get(key) != value:
        raise SystemExit(f"[FAIL] expected {key}={value!r}, got {row.get(key)!r}")

print("[OK] dispatcher requeue preserves case fields")
PY

cat <<'EOF' | bash "$AGENT_DIR/scripts/dispatcher.sh" "$DB" requeue >/dev/null
{"url":"https://app.example.com/orders/42?view=full","method":"GET","type":"page"}
EOF

minimal_row_json="$(sqlite3 -json "$DB" "SELECT method, url, url_path, query_params, body_params, path_params, cookie_params, headers, response_headers, type, source, status, params_key_sig FROM cases WHERE url = 'https://app.example.com/orders/42?view=full' LIMIT 1;")"

python3 - "$minimal_row_json" <<'PY'
import hashlib
import json
import sys

rows = json.loads(sys.argv[1])
if len(rows) != 1:
    raise SystemExit("[FAIL] expected minimal requeue row")

row = rows[0]
expected_sig = hashlib.md5("view".encode()).hexdigest()
expected = {
    "method": "GET",
    "url": "https://app.example.com/orders/42?view=full",
    "url_path": "/orders/42",
    "query_params": '{"view":"full"}',
    "body_params": "{}",
    "path_params": '{"seg_2":"42"}',
    "cookie_params": "{}",
    "headers": "{}",
    "response_headers": "{}",
    "type": "page",
    "source": "requeue",
    "status": "pending",
    "params_key_sig": expected_sig,
}

for key, value in expected.items():
    if row.get(key) != value:
        raise SystemExit(f"[FAIL] expected minimal {key}={value!r}, got {row.get(key)!r}")

print("[OK] dispatcher requeue derives defaults for minimal input")
PY
