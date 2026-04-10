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
  ('GET', 'https://example.test/page', '/page', 'page', 'seed', 'pending', datetime('now'), 'sig-page');
"

SUMMARY="$DB_DIR/summary.txt"
"$REPO_ROOT/agent/scripts/fetch_batch_to_file.sh" "$DB_PATH" api-spec 10 vulnerability-analyst "$OUT_FILE" >"$SUMMARY"

[[ -f "$OUT_FILE" ]] || { echo "expected batch output file" >&2; exit 1; }
[[ "$(jq -c . "$OUT_FILE")" == "[]" ]] || { echo "expected empty JSON array for zero-row batch" >&2; cat "$OUT_FILE" >&2; exit 1; }

grep -q '^BATCH_FILE='"$OUT_FILE"'$' "$SUMMARY" || { echo "missing BATCH_FILE summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_TYPE=api-spec$' "$SUMMARY" || { echo "missing BATCH_TYPE summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_AGENT=vulnerability-analyst$' "$SUMMARY" || { echo "missing BATCH_AGENT summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_COUNT=0$' "$SUMMARY" || { echo "missing BATCH_COUNT=0 summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_IDS=$' "$SUMMARY" || { echo "missing empty BATCH_IDS summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_PATHS=$' "$SUMMARY" || { echo "missing empty BATCH_PATHS summary" >&2; cat "$SUMMARY" >&2; exit 1; }
if grep -q '^BATCH_NOTE=' "$SUMMARY"; then
  echo "unexpected BATCH_NOTE for zero-row empty batch" >&2
  cat "$SUMMARY" >&2
  exit 1
fi

echo "PASS: fetch_batch_to_file normalizes zero-row fetches to an empty JSON batch"
