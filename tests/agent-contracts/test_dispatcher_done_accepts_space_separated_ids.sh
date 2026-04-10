#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_DIR="$(mktemp -d)"
DB_PATH="$DB_DIR/cases.db"
cleanup() {
  rm -rf "$DB_DIR"
}
trap cleanup EXIT

sqlite3 "$DB_PATH" < "$REPO_ROOT/agent/scripts/schema.sql"

sqlite3 "$DB_PATH" ".timeout 5000" "
INSERT INTO cases (method, url, url_path, type, source, status, created_at, params_key_sig)
VALUES
  ('GET', 'https://example.test/api/1', '/api/1', 'api', 'seed', 'processing', datetime('now'), 'sig-1'),
  ('GET', 'https://example.test/api/2', '/api/2', 'api', 'seed', 'processing', datetime('now'), 'sig-2'),
  ('GET', 'https://example.test/api/3', '/api/3', 'api', 'seed', 'processing', datetime('now'), 'sig-3');
"

OUT_DONE="$DB_DIR/done.out"
"$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" done 1 2 3 >"$OUT_DONE"
grep -q '^Marked done: 1,2,3$' "$OUT_DONE" || { echo "space-separated done IDs were not normalized" >&2; cat "$OUT_DONE" >&2; exit 1; }
DONE_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='done';")"
[[ "$DONE_COUNT" == "3" ]] || { echo "expected all three cases to be marked done" >&2; exit 1; }

sqlite3 "$DB_PATH" ".timeout 5000" "UPDATE cases SET status='processing';"
OUT_ERR="$DB_DIR/error.out"
"$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" error 1,2 3 >"$OUT_ERR"
grep -q '^Marked error: 1,2,3$' "$OUT_ERR" || { echo "mixed comma/space error IDs were not normalized" >&2; cat "$OUT_ERR" >&2; exit 1; }
ERROR_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='error';")"
[[ "$ERROR_COUNT" == "3" ]] || { echo "expected all three cases to be marked error" >&2; exit 1; }

BAD_OUT="$DB_DIR/bad.out"
if "$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" done 1 nope >"$BAD_OUT" 2>&1; then
  echo "expected invalid mixed IDs to fail" >&2
  exit 1
fi
grep -q 'numeric IDs separated by commas or spaces' "$BAD_OUT" || { echo "missing validation message for bad ids" >&2; cat "$BAD_OUT" >&2; exit 1; }

echo "PASS: dispatcher done/error normalize space-separated id lists"