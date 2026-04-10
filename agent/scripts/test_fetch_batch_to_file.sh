#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_DIR="$(mktemp -d)"
DB_PATH="$DB_DIR/cases.db"
OUT_FILE="$DB_DIR/batch.json"
cleanup() {
  rm -rf "$DB_DIR"
}
trap cleanup EXIT

sqlite3 "$DB_PATH" < "$REPO_ROOT/agent/scripts/schema.sql"

sqlite3 "$DB_PATH" ".timeout 5000" "
INSERT INTO cases (method, url, url_path, type, source, status, created_at, params_key_sig)
VALUES
  ('GET', 'https://example.test/api/a', '/api/a', 'api', 'seed', 'pending', datetime('now'), 'sig-a'),
  ('GET', 'https://example.test/api/b', '/api/b', 'api', 'seed', 'pending', datetime('now'), 'sig-b');
"

SUMMARY="$DB_DIR/summary.txt"
"$REPO_ROOT/agent/scripts/fetch_batch_to_file.sh" "$DB_PATH" api 10 vulnerability-analyst "$OUT_FILE" >"$SUMMARY"

[[ -f "$OUT_FILE" ]] || { echo "expected batch output file" >&2; exit 1; }
[[ "$(jq 'length' "$OUT_FILE")" == "2" ]] || { echo "expected 2 fetched rows" >&2; cat "$OUT_FILE" >&2; exit 1; }

grep -q '^BATCH_FILE='"$OUT_FILE"'$' "$SUMMARY" || { echo "missing BATCH_FILE summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_TYPE=api$' "$SUMMARY" || { echo "missing BATCH_TYPE summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_AGENT=vulnerability-analyst$' "$SUMMARY" || { echo "missing BATCH_AGENT summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_COUNT=2$' "$SUMMARY" || { echo "missing BATCH_COUNT summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_IDS=1,2$' "$SUMMARY" || { echo "missing BATCH_IDS summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_PATHS=/api/a,/api/b$' "$SUMMARY" || { echo "missing BATCH_PATHS summary" >&2; cat "$SUMMARY" >&2; exit 1; }

PROCESSING_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='vulnerability-analyst';")"
[[ "$PROCESSING_COUNT" == "2" ]] || { echo "expected two processing rows after fetch" >&2; exit 1; }

echo "PASS: fetch_batch_to_file writes JSON to disk and prints compact metadata only"
