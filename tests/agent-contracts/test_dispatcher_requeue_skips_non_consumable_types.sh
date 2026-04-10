#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR"

sqlite3 "$ENG_DIR/cases.db" < "$ROOT/agent/scripts/schema.sql"

cat <<'EOF' | "$ROOT/agent/scripts/dispatcher.sh" "$ENG_DIR/cases.db" requeue >/dev/null
{"method":"GET","url":"http://host.docker.internal:8000/static/logo.png","url_path":"/static/logo.png","type":"image","source":"katana"}
EOF

image_status="$(sqlite3 "$ENG_DIR/cases.db" "SELECT status FROM cases WHERE url = 'http://host.docker.internal:8000/static/logo.png';")"
if [[ "$image_status" != "skipped" ]]; then
  echo "FAIL: expected requeued image case to be skipped, got '$image_status'" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT id, type, source, status, url FROM cases ORDER BY id;" >&2
  exit 1
fi

sqlite3 "$ENG_DIR/cases.db" <<'EOF'
INSERT INTO cases (
  method, url, url_path,
  query_params, body_params, path_params, cookie_params,
  headers, body, content_type, content_length,
  response_status, response_headers, response_size, response_snippet,
  type, source, status, params_key_sig,
  assigned_agent, consumed_at
) VALUES (
  'GET', 'http://host.docker.internal:8000/static/banner.png', '/static/banner.png',
  '{}', '{}', '{}', '{}',
  '{}', '', '', 0,
  0, '{}', 0, '',
  'unknown', 'seed', 'processing', 'GET:/static/banner.png',
  'crawler', datetime('now', '-30 minutes')
);
EOF

cat <<'EOF' | "$ROOT/agent/scripts/dispatcher.sh" "$ENG_DIR/cases.db" requeue >/dev/null
{"method":"GET","url":"http://host.docker.internal:8000/static/banner.png","url_path":"/static/banner.png","type":"image","source":"katana","params_key_sig":"GET:/static/banner.png"}
EOF

upgraded_row="$(sqlite3 -separator '|' "$ENG_DIR/cases.db" "SELECT type, status, assigned_agent IS NULL, consumed_at IS NULL FROM cases WHERE url = 'http://host.docker.internal:8000/static/banner.png';")"
if [[ "$upgraded_row" != "image|skipped|1|1" ]]; then
  echo "FAIL: expected unknown processing row to upgrade to image/skipped and clear assignment, got '$upgraded_row'" >&2
  sqlite3 "$ENG_DIR/cases.db" "SELECT id, type, source, status, assigned_agent, consumed_at, url FROM cases ORDER BY id;" >&2
  exit 1
fi

echo "PASS: dispatcher requeue keeps non-consumable cases skipped"