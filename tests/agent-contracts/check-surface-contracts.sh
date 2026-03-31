#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
APPEND_SCRIPT="$ROOT_DIR/agent/scripts/append_surface.sh"
CHECK_SCRIPT="$ROOT_DIR/agent/scripts/check_surface_coverage.sh"

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

main() {
  need_script "$APPEND_SCRIPT"
  need_script "$CHECK_SCRIPT"
  test_append_and_dedup_update
  test_status_update_to_covered
  test_candidate_status_normalizes_to_discovered
  test_coverage_check_fails_on_unresolved_discovered
  echo "surface contracts: ok"
}

main "$@"
