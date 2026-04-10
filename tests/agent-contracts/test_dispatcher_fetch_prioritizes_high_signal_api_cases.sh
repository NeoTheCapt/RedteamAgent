#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_DIR="$(mktemp -d)"
DB_PATH="$DB_DIR/cases.db"
FETCH_JSON="$DB_DIR/fetch.json"
cleanup() {
  rm -rf "$DB_DIR"
}
trap cleanup EXIT

sqlite3 "$DB_PATH" < "$REPO_ROOT/agent/scripts/schema.sql"

sqlite3 "$DB_PATH" ".timeout 5000" "
INSERT INTO cases (method, url, url_path, type, source, status, query_params, body_params, created_at, params_key_sig)
VALUES
  ('GET', 'https://example.test/rest/chatbot/status', '/rest/chatbot/status', 'api', 'source-analyzer', 'pending', '{}', '{}', datetime('now'), 'sig-chatbot'),
  ('GET', 'https://example.test/rest/country-mapping', '/rest/country-mapping', 'api', 'source-analyzer', 'pending', '{}', '{}', datetime('now'), 'sig-country'),
  ('POST', 'https://example.test/rest/user/login', '/rest/user/login', 'api', 'source-analyzer', 'pending', '{}', '{\"email\":\"demo@example.test\",\"password\":\"Password123!\"}', datetime('now'), 'sig-login'),
  ('GET', 'https://example.test/rest/wallet/balance', '/rest/wallet/balance', 'api', 'exploit-developer', 'pending', '{}', '{}', datetime('now'), 'sig-wallet'),
  ('GET', 'https://example.test/api/Cards', '/api/Cards', 'api', 'exploit-developer', 'pending', '{}', '{}', datetime('now'), 'sig-cards');
"

"$REPO_ROOT/agent/scripts/dispatcher.sh" "$DB_PATH" fetch api 3 vulnerability-analyst >"$FETCH_JSON"

SELECTED_IDS="$(jq -r 'map(.id) | sort | join(",")' "$FETCH_JSON")"
if [[ "$SELECTED_IDS" != "3,4,5" ]]; then
  echo "Expected high-signal API cases (login, wallet, cards) to be selected first; got ids=$SELECTED_IDS" >&2
  cat "$FETCH_JSON" >&2
  exit 1
fi

LOW_SIGNAL_PENDING="$(sqlite3 "$DB_PATH" "SELECT group_concat(id, ',') FROM cases WHERE status='pending' ORDER BY id;")"
if [[ "$LOW_SIGNAL_PENDING" != "1,2" ]]; then
  echo "Expected low-signal API cases to remain pending; got pending ids=$LOW_SIGNAL_PENDING" >&2
  exit 1
fi

PROCESSING_COUNT="$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='vulnerability-analyst';")"
if [[ "$PROCESSING_COUNT" != "3" ]]; then
  echo "Expected exactly three processing rows for vulnerability-analyst; got count=$PROCESSING_COUNT" >&2
  exit 1
fi

echo "PASS: dispatcher fetch prioritizes high-signal API cases ahead of low-yield backlog"
