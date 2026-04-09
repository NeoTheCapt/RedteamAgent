#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
APPEND_SCRIPT="$ROOT_DIR/agent/scripts/append_surface.sh"
CHECK_SCRIPT="$ROOT_DIR/agent/scripts/check_surface_coverage.sh"
RECONCILE_SCRIPT="$ROOT_DIR/agent/scripts/reconcile_surface_coverage.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_script() {
  [[ -x "$1" ]] || fail "missing executable script: $1"
}

make_engagement_dir() {
  local dir
  dir=$(mktemp -d "${TMPDIR:-/tmp}/surface-contracts.XXXXXX")
  : >"$dir/surfaces.jsonl"
  printf '%s\n' "$dir"
}

test_append_and_dedup_update() {
  local dir
  dir=$(make_engagement_dir)

  "$APPEND_SCRIPT" "$dir" auth_entry 'POST /rest/user/login' source-analyzer \
    'public bundle exposes login workflow' 'downloads/source-analysis/assets/main.js'
  "$APPEND_SCRIPT" "$dir" auth_entry 'POST /rest/user/login' recon-specialist \
    'login endpoint observed during recon' 'downloads/root.html'

  local count
  count=$(wc -l <"$dir/surfaces.jsonl" | tr -d ' ')
  [[ "$count" == "1" ]] || fail "expected deduped single surface record, got $count"

  python3 - <<'PY' "$dir/surfaces.jsonl"
import json,sys
rows=[json.loads(line) for line in open(sys.argv[1]) if line.strip()]
assert len(rows)==1, rows
row=rows[0]
assert row["surface_type"]=="auth_entry", row
assert row["target"]=="POST /rest/user/login", row
assert row["status"]=="discovered", row
assert row["source"]=="recon-specialist", row
PY

  rm -rf "$dir"
}

test_status_update_to_covered() {
  local dir
  dir=$(make_engagement_dir)

  "$APPEND_SCRIPT" "$dir" object_reference 'GET /api/Users/:id' recon-specialist \
    'adjacent-id object route discovered' '' discovered
  "$APPEND_SCRIPT" "$dir" object_reference 'GET /api/Users/:id' operator \
    'representative IDOR validation completed' 'scans/idor-users-2.body' covered

  python3 - <<'PY' "$dir/surfaces.jsonl"
import json,sys
rows=[json.loads(line) for line in open(sys.argv[1]) if line.strip()]
assert len(rows)==1, rows
row=rows[0]
assert row["status"]=="covered", row
assert row["evidence_ref"]=="scans/idor-users-2.body", row
PY

  rm -rf "$dir"
}

test_candidate_status_normalizes_to_discovered() {
  local dir out
  dir=$(make_engagement_dir)

  "$APPEND_SCRIPT" "$dir" workflow_token 'POST /rest/2fa/verify' source-analyzer \
    'frontend bundle exposes MFA verification flow' 'downloads/assets/main.js:666' candidate

  python3 - <<'PY' "$dir/surfaces.jsonl"
import json,sys
rows=[json.loads(line) for line in open(sys.argv[1]) if line.strip()]
assert len(rows)==1, rows
row=rows[0]
assert row["status"]=="discovered", row
assert row["surface_type"]=="workflow_token", row
PY

  out=$(mktemp "${TMPDIR:-/tmp}/surface-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    raise_error=1
  else
    raise_error=0
  fi
  [[ "$raise_error" == "0" ]] || fail "coverage check should fail while candidate/discovered surface remains unresolved"
  rg 'Uncovered surfaces remain' "$out" >/dev/null || fail "missing uncovered surfaces failure output for candidate alias"

  rm -f "$out"
  rm -rf "$dir"
}

test_coverage_check_fails_on_unresolved_discovered() {
  local dir out
  dir=$(make_engagement_dir)
  "$APPEND_SCRIPT" "$dir" api_documentation 'GET /api-docs' source-analyzer \
    'public swagger route discovered' 'downloads/swagger-ui-init.js' discovered

  out=$(mktemp "${TMPDIR:-/tmp}/surface-check.XXXXXX")
  if "$CHECK_SCRIPT" "$dir" >"$out" 2>&1; then
    cat "$out" >&2
    fail "coverage check should fail when discovered surfaces remain unresolved"
  fi
  rg 'Uncovered surfaces remain' "$out" >/dev/null || fail "missing uncovered surfaces failure output"

  "$APPEND_SCRIPT" "$dir" api_documentation 'GET /api-docs' operator \
    'deferred pending manual validation' '' deferred >/dev/null
  "$CHECK_SCRIPT" "$dir" >/dev/null || fail "coverage check should pass after status resolution"

  rm -f "$out"
  rm -rf "$dir"
}

test_reconcile_marks_advisory_surfaces_not_applicable_and_queues_concrete_followups() {
  local dir out
  dir=$(make_engagement_dir)

  cat >"$dir/scope.json" <<'EOF'
{
  "target": "https://www.okx.com",
  "hostname": "www.okx.com",
  "port": 443,
  "scope": ["www.okx.com", "*.www.okx.com"],
  "status": "in_progress",
  "current_phase": "consume_test"
}
EOF

  cat >"$dir/findings.md" <<'EOF'
# Findings
EOF

  python3 - <<'PY' "$dir/cases.db"
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("CREATE TABLE cases (method TEXT, url TEXT, url_path TEXT, query_params TEXT, type TEXT, status TEXT)")
conn.commit()
conn.close()
PY

  cat >"$dir/surfaces.jsonl" <<'EOF'
{"surface_type":"auth_entry","target":"GET https://my.okx.com/en-sg/account/login","source":"source-analyzer","rationale":"out-of-scope auth host","status":"discovered"}
{"surface_type":"workflow_token","target":"Client cookie names: token, im-token, ok-ses-id, _tk","source":"source-analyzer","rationale":"advisory cookie names only","status":"discovered"}
{"surface_type":"file_handling","target":"GET /en-sg/download","source":"source-analyzer","rationale":"download center route","status":"discovered"}
{"surface_type":"privileged_write","target":"POST https://www.okx.com/priapi/v5/balance/reset","source":"source-analyzer","rationale":"balance reset write flow","status":"discovered"}
EOF

  out=$(mktemp "${TMPDIR:-/tmp}/surface-reconcile.XXXXXX")
  "$RECONCILE_SCRIPT" "$dir" >"$out"
  rg 'auto-resolved 2 surface\(s\)' "$out" >/dev/null || fail "expected advisory/out-of-scope surfaces to auto-resolve"
  rg 'queued 2 concrete follow-up case\(s\)' "$out" >/dev/null || fail "expected concrete follow-up cases to be queued"

  python3 - <<'PY' "$dir/surfaces.jsonl" "$dir/scans/surface-coverage-followups.jsonl"
import json, sys
surfaces = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]
followups = [json.loads(line) for line in open(sys.argv[2], encoding='utf-8') if line.strip()]
rows = {row['target']: row for row in surfaces}
assert rows['GET https://my.okx.com/en-sg/account/login']['status'] == 'not_applicable', rows
assert rows['Client cookie names: token, im-token, ok-ses-id, _tk']['status'] == 'not_applicable', rows
assert rows['GET /en-sg/download']['status'] == 'discovered', rows
assert rows['POST https://www.okx.com/priapi/v5/balance/reset']['status'] == 'discovered', rows
assert any(item['url'] == 'https://www.okx.com/en-sg/download' and item['type'] == 'page' for item in followups), followups
assert any(item['url'] == 'https://www.okx.com/priapi/v5/balance/reset' and item['type'] == 'api' and item['method'] == 'POST' for item in followups), followups
PY

  rm -f "$out"
  rm -rf "$dir"
}

main() {
  need_script "$APPEND_SCRIPT"
  need_script "$CHECK_SCRIPT"
  need_script "$RECONCILE_SCRIPT"
  test_append_and_dedup_update
  test_status_update_to_covered
  test_candidate_status_normalizes_to_discovered
  test_coverage_check_fails_on_unresolved_discovered
  test_reconcile_marks_advisory_surfaces_not_applicable_and_queues_concrete_followups
  echo "surface contracts: ok"
}

main "$@"
