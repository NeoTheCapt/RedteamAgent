#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/finalize-observation.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

make_engagement() {
  local eng_dir="$1"
  local target="$2"
  local hostname="$3"
  mkdir -p "$eng_dir"
  cat >"$eng_dir/scope.json" <<EOF
{
  "target": "$target",
  "hostname": "$hostname",
  "status": "in_progress",
  "current_phase": "report",
  "start_time": "2026-04-09T21:23:01Z",
  "phases_completed": ["recon", "collect", "consume_test", "exploit"]
}
EOF
  cat >"$eng_dir/log.md" <<'EOF'
# Log
- **Status**: In Progress
EOF
  cat >"$eng_dir/report.md" <<EOF
# Penetration Test Report: $target
**Date**: 2026-04-09 — In Progress
**Target**: $target  **Scope**: test  **Status**: In Progress
EOF
}

standard_eng="$TMP_DIR/standard"
make_engagement "$standard_eng" "https://example.com" "example.com"
"$REPO_ROOT/scripts/finalize_engagement.sh" "$standard_eng"

jq -e '.status == "complete" and .current_phase == "complete" and (.phases_completed | index("report") != null) and (.end_time | type == "string")' "$standard_eng/scope.json" >/dev/null
rg -q '^- \*\*Status\*\*: Completed$' "$standard_eng/log.md"
rg -q '^\*\*Date\*\*: .* — Completed$' "$standard_eng/report.md"
rg -q '^\*\*Target\*\*: .*\*\*Status\*\*: Completed$' "$standard_eng/report.md"

continuous_eng="$TMP_DIR/continuous"
continuous_out="$TMP_DIR/continuous.out"
make_engagement "$continuous_eng" "https://www.okx.com" "www.okx.com"

python3 - <<'PY' "$REPO_ROOT" "$continuous_eng" "$continuous_out"
import os
import subprocess
import sys
import time

repo_root, eng_dir, out_path = sys.argv[1:4]
env = os.environ.copy()
env["REDTEAM_CONTINUOUS_TARGETS"] = "https://www.okx.com"
env["OBSERVATION_SECONDS"] = "1"
with open(out_path, "w", encoding="utf-8") as handle:
    proc = subprocess.Popen(
        [f"{repo_root}/scripts/finalize_engagement.sh", eng_dir],
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    time.sleep(2.2)
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
PY

jq -e '.status == "in_progress" and .current_phase == "report" and (.phases_completed | index("report") != null) and (.end_time | not)' "$continuous_eng/scope.json" >/dev/null
rg -q '^- \*\*Status\*\*: In Progress$' "$continuous_eng/log.md"
rg -q '^\*\*Date\*\*: .* — In Progress$' "$continuous_eng/report.md"
rg -q '^\*\*Target\*\*: .*\*\*Status\*\*: In Progress$' "$continuous_eng/report.md"
rg -q '\[observation\] Continuous observation hold active for https://www.okx.com' "$continuous_out"
rg -q '\[observation\] .* heartbeat=1s' "$continuous_out"

echo "PASS: finalize_engagement respects continuous observation target matching"
