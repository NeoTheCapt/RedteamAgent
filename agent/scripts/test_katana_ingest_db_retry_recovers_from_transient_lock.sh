#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DB_PATH="$TMP_DIR/cases.db"
sqlite3 "$DB_PATH" < "$ROOT/agent/scripts/schema.sql"

python3 - <<'PY' "$DB_PATH" &
import sqlite3
import sys
import time

db_path = sys.argv[1]
conn = sqlite3.connect(db_path, timeout=1.0)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("BEGIN EXCLUSIVE")
time.sleep(6)
conn.rollback()
conn.close()
PY
locker_pid=$!

sleep 1

# shellcheck disable=SC1090
source "$ROOT/agent/scripts/lib/db.sh"

start_epoch="$(date +%s)"
changes="$(db_insert_case "$DB_PATH" \
  "GET" \
  "http://host.docker.internal:8000/api/lock-test" \
  "/api/lock-test" \
  "{}" \
  "{}" \
  "{}" \
  "{}" \
  "" \
  "" \
  "application/json" \
  "0" \
  "200" \
  "" \
  "0" \
  "" \
  "api" \
  "katana" \
  "{}")"
end_epoch="$(date +%s)"

wait "$locker_pid"

changes="$(printf '%s' "$changes" | tr -d '[:space:]')"
if [[ "$changes" != "1" ]]; then
  echo "FAIL: expected db_insert_case to succeed after transient lock, got: $changes" >&2
  exit 1
fi

elapsed=$((end_epoch - start_epoch))
if (( elapsed < 5 )); then
  echo "FAIL: expected db_insert_case to wait/retry through the lock window, elapsed=${elapsed}s" >&2
  exit 1
fi

count="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE url = 'http://host.docker.internal:8000/api/lock-test';")"
if [[ "$count" != "1" ]]; then
  echo "FAIL: expected retried insert to land exactly once, got $count" >&2
  exit 1
fi

echo "PASS: db_insert_case retries through transient sqlite locks and lands the case once"
