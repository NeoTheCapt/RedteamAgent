#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

SCRIPT="$ROOT/agent/scripts/reconcile_surface_coverage.sh"
SCHEMA="$ROOT/agent/scripts/schema.sql"

init_eng() {
  local eng_dir="$1"
  mkdir -p "$eng_dir/scans"
  cat > "$eng_dir/scope.json" <<'EOF'
{
  "target": "https://www.okx.com",
  "hostname": "www.okx.com",
  "scope": ["www.okx.com", "*.www.okx.com"],
  "status": "in_progress",
  "current_phase": "consume_test"
}
EOF
  cat > "$eng_dir/findings.md" <<'EOF'
# Findings
EOF
  cat > "$eng_dir/auth.json" <<'EOF'
{}
EOF
  : > "$eng_dir/surfaces.jsonl"
  sqlite3 "$eng_dir/cases.db" < "$SCHEMA"
}

insert_case() {
  local eng_dir="$1"
  local method="$2"
  local url="$3"
  local url_path="$4"
  local source="$5"
  local status="$6"
  sqlite3 "$eng_dir/cases.db" <<EOF
INSERT INTO cases(method, url, url_path, query_params, type, source, status, params_key_sig)
VALUES('$method', '$url', '$url_path', '{}', 'page', '$source', '$status', '');
EOF
}

queue_eng="$TMP_DIR/queue-eng"
init_eng "$queue_eng"
insert_case "$queue_eng" "GET" "https://www.okx.com/en-sg/help" "/en-sg/help" "katana" "done"
cat > "$queue_eng/surfaces.jsonl" <<'EOF'
{"surface_type":"account_recovery","target":"GET locale-scoped /account/login-pwd/forget","source":"test-suite","rationale":"robots locale route","evidence_ref":"downloads/robots.txt","status":"discovered"}
EOF
"$SCRIPT" "$queue_eng"
python3 - <<'PY' "$queue_eng"
import json, sys
from pathlib import Path
eng = Path(sys.argv[1])
followups = [json.loads(line) for line in (eng / 'scans' / 'surface-coverage-followups.jsonl').read_text().splitlines() if line.strip()]
assert len(followups) == 1, followups
row = followups[0]
assert row['url'] == 'https://www.okx.com/en-sg/account/login-pwd/forget', row
assert row['url_path'] == '/en-sg/account/login-pwd/forget', row
assert 'locale-scoped' not in row['url'], row
assert 'locale-scoped' not in row['url_path'], row
PY

cover_eng="$TMP_DIR/cover-eng"
init_eng "$cover_eng"
insert_case "$cover_eng" "GET" "https://www.okx.com/en-sg/account/login-pwd/forget" "/en-sg/account/login-pwd/forget" "katana" "done"
cat > "$cover_eng/surfaces.jsonl" <<'EOF'
{"surface_type":"account_recovery","target":"GET locale-scoped /account/login-pwd/forget","source":"test-suite","rationale":"robots locale route","evidence_ref":"downloads/robots.txt","status":"discovered"}
EOF
"$SCRIPT" "$cover_eng"
python3 - <<'PY' "$cover_eng"
import json, sys
from pathlib import Path
eng = Path(sys.argv[1])
rows = [json.loads(line) for line in (eng / 'surfaces.jsonl').read_text().splitlines() if line.strip()]
match = [row for row in rows if row.get('target') == 'GET locale-scoped /account/login-pwd/forget' and row.get('source') == 'operator-surface-coverage' and row.get('status') == 'covered']
assert len(match) == 1, rows
followups = (eng / 'scans' / 'surface-coverage-followups.jsonl').read_text().strip()
assert followups == '', followups
PY

echo "PASS: reconcile_surface_coverage handles locale-scoped targets without malformed follow-up URLs"
