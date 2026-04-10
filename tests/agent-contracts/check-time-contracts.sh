#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TIME_LIB="$ROOT_DIR/agent/scripts/lib/time.sh"
FINALIZE_SCRIPT="$ROOT_DIR/agent/scripts/finalize_engagement.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_file() {
  [[ -f "$1" ]] || fail "missing file: $1"
}

make_engagement_dir() {
  local dir
  dir=$(mktemp -d "${TMPDIR:-/tmp}/time-contracts.XXXXXX")
  cat >"$dir/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "mode": "ctf",
  "status": "in_progress",
  "start_time": "2026-03-22T20:28:55Z",
  "phases_completed": ["recon", "collect", "test", "exploit"],
  "current_phase": "report"
}
EOF

  cat >"$dir/log.md" <<'EOF'
# Engagement Log

- **Target**: http://127.0.0.1:8000
- **Date**: 2026-03-23
- **Mode**: CTF
- **Status**: In Progress

---
EOF

  cat >"$dir/report.md" <<'EOF'
# Penetration Test Report: http://127.0.0.1:8000
**Date**: 2026-03-22 — In Progress
**Target**: http://127.0.0.1:8000  **Scope**: 127.0.0.1, *.127.0.0.1  **Status**: In Progress

---
EOF

  sqlite3 "$dir/cases.db" "CREATE TABLE cases (id INTEGER PRIMARY KEY, status TEXT);" >/dev/null
  printf '%s\n' "$dir"
}

test_report_header_date_derives_from_scope_start_time() {
  local dir
  dir=$(make_engagement_dir)

  TZ=Asia/Singapore "$FINALIZE_SCRIPT" "$dir"

  rg '^\*\*Date\*\*: 2026-03-23 — Completed$' "$dir/report.md" >/dev/null || fail "report date should derive from scope/log unified helper output"
  rg '^\- \*\*Date\*\*: 2026-03-23$' "$dir/log.md" >/dev/null || fail "log date unexpectedly changed"

  rm -rf "$dir"
}

main() {
  need_file "$TIME_LIB"
  test_report_header_date_derives_from_scope_start_time
  echo "time contracts: ok"
}

main "$@"
