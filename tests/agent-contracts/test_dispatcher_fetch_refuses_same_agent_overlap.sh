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
INSERT INTO cases (method, url, url_path, type, source, status, assigned_agent, consumed_at, created_at, params_key_sig)
VALUES ('GET', 'https://example.test/already-processing', '/already-processing', 'api', 'seed', 'processing', 'vulnerability-analyst', datetime('now'), datetime('now'), 'sig-processing');
INSERT INTO cases (method, url, url_path, type, source, status, created_at, params_key_sig)
VALUES ('GET', 'https://example.test/pending-api', '/pending-api', 'api', 'seed', 'pending', datetime('now'), 'sig-pending');
"

FETCH_STDOUT="$DB_DIR/fetch.stdout"
FETCH_STDERR="$DB_DIR/fetch.stderr"
"$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" fetch api 10 vulnerability-analyst >"$FETCH_STDOUT" 2>"$FETCH_STDERR"

if [[ "$(tr -d '\n[:space:]' < "$FETCH_STDOUT")" != "[]" ]]; then
  echo "Expected fetch stdout to be [] when the same agent already has processing cases" >&2
  cat "$FETCH_STDOUT" >&2
  exit 1
fi

if ! grep -q "Refusing fetch for vulnerability-analyst" "$FETCH_STDERR"; then
  echo "Expected refusal message on stderr" >&2
  cat "$FETCH_STDERR" >&2
  exit 1
fi

PENDING_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='pending' AND assigned_agent IS NULL;")"
PROCESSING_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='vulnerability-analyst';")"
if [[ "$PENDING_COUNT" != "1" ]]; then
  echo "Expected pending case to stay pending; got count=$PENDING_COUNT" >&2
  exit 1
fi
if [[ "$PROCESSING_COUNT" != "1" ]]; then
  echo "Expected only the original processing case for vulnerability-analyst; got count=$PROCESSING_COUNT" >&2
  exit 1
fi

OTHER_STDOUT="$DB_DIR/other.stdout"
"$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" fetch api 10 source-analyzer >"$OTHER_STDOUT"
if ! grep -q '"assigned_agent":"source-analyzer"' "$OTHER_STDOUT"; then
  echo "Expected fetch for a different agent to proceed" >&2
  cat "$OTHER_STDOUT" >&2
  exit 1
fi

OTHER_PROCESSING_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='source-analyzer';")"
if [[ "$OTHER_PROCESSING_COUNT" != "1" ]]; then
  echo "Expected one processing case for source-analyzer after allowed fetch; got count=$OTHER_PROCESSING_COUNT" >&2
  exit 1
fi

echo "PASS: dispatcher fetch blocks same-agent overlap and preserves pending rows"
