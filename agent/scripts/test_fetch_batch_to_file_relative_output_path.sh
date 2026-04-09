#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
DB_PATH="$TMP_DIR/cases.db"
WORK_DIR="$TMP_DIR/workspace"
REL_OUT="scans/batches/upload-001.json"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$WORK_DIR"
sqlite3 "$DB_PATH" < "$REPO_ROOT/agent/scripts/schema.sql"

sqlite3 "$DB_PATH" ".timeout 5000" "
INSERT INTO cases (method, url, url_path, type, source, status, created_at, params_key_sig)
VALUES
  ('POST', 'https://example.test/file-upload', '/file-upload', 'upload', 'seed', 'pending', datetime('now'), 'sig-upload');
"

SUMMARY="$TMP_DIR/summary.txt"
(
  cd "$WORK_DIR"
  "$REPO_ROOT/agent/scripts/fetch_batch_to_file.sh" "$DB_PATH" upload 10 vulnerability-analyst "$REL_OUT" >"$SUMMARY"
)

EXPECTED_OUT="$WORK_DIR/$REL_OUT"
[[ -f "$EXPECTED_OUT" ]] || { echo "expected relative batch output file at $EXPECTED_OUT" >&2; exit 1; }
[[ "$(jq 'length' "$EXPECTED_OUT")" == "1" ]] || { echo "expected 1 fetched row" >&2; cat "$EXPECTED_OUT" >&2; exit 1; }

grep -q '^BATCH_FILE='"$EXPECTED_OUT"'$' "$SUMMARY" || { echo "expected workspace-local BATCH_FILE summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_COUNT=1$' "$SUMMARY" || { echo "missing BATCH_COUNT=1 summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_IDS=1$' "$SUMMARY" || { echo "missing BATCH_IDS=1 summary" >&2; cat "$SUMMARY" >&2; exit 1; }
grep -q '^BATCH_PATHS=/file-upload$' "$SUMMARY" || { echo "missing BATCH_PATHS summary" >&2; cat "$SUMMARY" >&2; exit 1; }

echo "PASS: fetch_batch_to_file keeps relative output paths inside the workspace"