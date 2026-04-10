#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DB_PATH="$TMP_DIR/cases.db"
sqlite3 "$DB_PATH" < "$ROOT/agent/scripts/schema.sql"

sqlite3 "$DB_PATH" ".timeout 5000" "
INSERT INTO cases (method, url, url_path, type, source, status, assigned_agent, consumed_at, created_at, params_key_sig)
VALUES
  ('GET', 'https://example.test/api/search?q=1', '/api/search', 'api', 'katana', 'processing', 'vulnerability-analyst', datetime('now'), datetime('now'), 'sig-1'),
  ('GET', 'https://example.test/#/search?q=1', '/#/search', 'page', 'source-analyzer', 'processing', 'source-analyzer', datetime('now'), datetime('now'), 'sig-2');
"

OUT_FILE="$TMP_DIR/requeue.out"
"$ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" requeue 1 2 "Higher-risk families remain" >"$OUT_FILE"
grep -q '^Requeued existing: 1,2$' "$OUT_FILE" || {
  echo "FAIL: dispatcher did not acknowledge existing-ID requeue" >&2
  cat "$OUT_FILE" >&2
  exit 1
}

sqlite3 "$DB_PATH" ".timeout 5000" "SELECT id, status, COALESCE(assigned_agent,''), COALESCE(consumed_at,'') FROM cases ORDER BY id;" >"$TMP_DIR/status.txt"
expected=$'1|pending||\n2|pending||'
actual="$(cat "$TMP_DIR/status.txt")"
if [[ "$actual" != "$expected" ]]; then
  echo "FAIL: existing cases were not reset to pending/unassigned" >&2
  cat "$TMP_DIR/status.txt" >&2
  exit 1
fi

echo "PASS: dispatcher requeue accepts existing case ids with trailing reason text"
