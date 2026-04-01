#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCHER="$SCRIPT_DIR/dispatcher.sh"

DB_PATH="${1:?usage: fetch_batch_to_file.sh <db_path> <type> <limit> <agent> <out_file>}"
BATCH_TYPE="${2:?usage: fetch_batch_to_file.sh <db_path> <type> <limit> <agent> <out_file>}"
BATCH_LIMIT="${3:?usage: fetch_batch_to_file.sh <db_path> <type> <limit> <agent> <out_file>}"
BATCH_AGENT="${4:?usage: fetch_batch_to_file.sh <db_path> <type> <limit> <agent> <out_file>}"
OUT_FILE_RAW="${5:?usage: fetch_batch_to_file.sh <db_path> <type> <limit> <agent> <out_file>}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "database not found: $DB_PATH" >&2
    exit 1
fi

if [[ "$OUT_FILE_RAW" = /* ]]; then
    OUT_FILE="$OUT_FILE_RAW"
else
    OUT_FILE="$(cd "$(dirname "$OUT_FILE_RAW")" 2>/dev/null && pwd)/$(basename "$OUT_FILE_RAW")"
fi

mkdir -p "$(dirname "$OUT_FILE")"

stderr_file="$(mktemp "${TMPDIR:-/tmp}/fetch-batch-stderr.XXXXXX")"
trap 'rm -f "$stderr_file"' EXIT

"$DISPATCHER" "$DB_PATH" fetch "$BATCH_TYPE" "$BATCH_LIMIT" "$BATCH_AGENT" >"$OUT_FILE" 2>"$stderr_file"

# sqlite3 -json UPDATE ... RETURNING emits an empty file (not "[]") when no rows
# match. Treat that as a valid empty batch so the operator can continue scanning
# batch types without surfacing a spurious helper failure.
if [[ ! -s "$OUT_FILE" ]]; then
    printf '[]\n' >"$OUT_FILE"
fi

if ! jq -e type "$OUT_FILE" >/dev/null 2>&1; then
    echo "dispatcher produced invalid JSON for batch fetch" >&2
    cat "$OUT_FILE" >&2 || true
    exit 1
fi

batch_count="$(jq 'length' "$OUT_FILE")"
if [[ "$batch_count" == "0" ]]; then
    batch_ids=""
    batch_paths=""
else
    batch_ids="$(jq -r 'map(.id | tostring) | join(",")' "$OUT_FILE")"
    batch_paths="$(jq -r 'map(.url_path // .url // "") | join(",")' "$OUT_FILE")"
fi

printf 'BATCH_FILE=%s\n' "$OUT_FILE"
printf 'BATCH_TYPE=%s\n' "$BATCH_TYPE"
printf 'BATCH_AGENT=%s\n' "$BATCH_AGENT"
printf 'BATCH_COUNT=%s\n' "$batch_count"
printf 'BATCH_IDS=%s\n' "$batch_ids"
printf 'BATCH_PATHS=%s\n' "$batch_paths"

if [[ -s "$stderr_file" ]]; then
    printf 'BATCH_NOTE=%s\n' "$(tr '\n' ' ' < "$stderr_file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
fi
