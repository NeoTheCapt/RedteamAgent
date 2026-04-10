#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
STORE_SCRIPT="$ROOT_DIR/agent/scripts/store_intel_secret.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_script() {
  [[ -x "$1" ]] || fail "missing executable script: $1"
}

make_engagement_dir() {
  local dir
  dir=$(mktemp -d "${TMPDIR:-/tmp}/intel-secret-contracts.XXXXXX")
  : >"$dir/intel-secrets.json"
  printf '%s\n' "$dir"
}

test_store_full_value_and_emit_summary_row() {
  local dir out
  dir=$(make_engagement_dir)
  out=$("$STORE_SCRIPT" "$dir" admin_jwt_01 jwt \
    'eyJhbGciOiJSUzI1NiJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature' \
    'auth.json' 'verified admin token')

  python3 - <<'PY' "$dir/intel-secrets.json"
import json,sys
rows=json.load(open(sys.argv[1]))
assert len(rows)==1, rows
row=rows[0]
assert row["ref"]=="admin_jwt_01", row
assert row["type"]=="jwt", row
assert row["value"]=="eyJhbGciOiJSUzI1NiJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature", row
assert row["source"]=="auth.json", row
PY

  [[ "$out" == *"| jwt | eyJhbGciOiJSUzI1NiJ9..."* ]] || fail "missing truncated preview in markdown row"
  [[ "$out" == *"| admin_jwt_01 | auth.json | verified admin token |"* ]] || fail "missing ref/source/notes in markdown row"

  rm -rf "$dir"
}

main() {
  need_script "$STORE_SCRIPT"
  test_store_full_value_and_emit_summary_row
  echo "intel secret contracts: ok"
}

main "$@"
