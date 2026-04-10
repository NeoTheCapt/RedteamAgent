#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
FINALIZE_SCRIPT="$ROOT_DIR/agent/scripts/finalize_engagement.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

need_script() {
  [[ -x "$1" ]] || fail "missing executable script: $1"
}

make_engagement_dir() {
  local dir
  dir=$(mktemp -d "${TMPDIR:-/tmp}/finalize-contracts.XXXXXX")
  cat >"$dir/scope.json" <<'EOF'
{
  "target": "http://127.0.0.1:8000",
  "hostname": "127.0.0.1",
  "port": 8000,
  "scope": ["127.0.0.1", "*.127.0.0.1"],
  "mode": "ctf",
  "status": "in_progress",
  "start_time": "2026-03-23T04:28:55Z",
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
**Status**: In Progress (testing queue completed; report phase active)

---
EOF

  sqlite3 "$dir/cases.db" "PRAGMA journal_mode=WAL; CREATE TABLE cases (id INTEGER PRIMARY KEY, status TEXT); INSERT INTO cases(status) VALUES ('done');" >/dev/null
  sqlite3 "$dir/cases.db" "INSERT INTO cases(status) VALUES ('done');"

  printf '%s\n' "$dir"
}

test_finalize_updates_status_and_dates() {
  local dir
  dir=$(make_engagement_dir)

  "$FINALIZE_SCRIPT" "$dir"

  python3 - <<'PY' "$dir/scope.json"
import json,sys
obj=json.load(open(sys.argv[1]))
assert obj["status"]=="complete", obj
assert obj["current_phase"]=="complete", obj
assert "report" in obj["phases_completed"], obj
assert obj.get("end_time"), obj
PY

  rg '^\- \*\*Status\*\*: Completed$' "$dir/log.md" >/dev/null || fail "log status not updated"
  rg '^\*\*Date\*\*: 2026-03-23 — Completed$' "$dir/report.md" >/dev/null || fail "report date/status not normalized"
  rg -F '**Target**: http://127.0.0.1:8000  **Scope**: 127.0.0.1, *.127.0.0.1  **Status**: Completed' "$dir/report.md" >/dev/null || fail "report target/status line not updated"
  rg '^\*\*Status\*\*: Completed$' "$dir/report.md" >/dev/null || fail "standalone report status line not updated"
  ! rg -n 'In Progress' "$dir/report.md" >/dev/null || fail "stale in-progress report status should be removed"

  [[ ! -f "$dir/cases.db-wal" ]] || fail "cases.db-wal should be removed after checkpoint"
  [[ ! -f "$dir/cases.db-shm" ]] || fail "cases.db-shm should be removed after checkpoint"

  rm -rf "$dir"
}

main() {
  need_script "$FINALIZE_SCRIPT"
  test_finalize_updates_status_and_dates
  echo "finalize contracts: ok"
}

main "$@"
