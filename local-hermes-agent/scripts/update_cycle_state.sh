#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
mkdir -p "$STATE_DIR"

LAST_COMMIT="${1:-}"
LAST_CYCLE_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_INVOCATION_ID="${HERMES_RUN_INVOCATION_ID:-}"
CYCLE_STATUS="${CYCLE_STATUS:-unknown}"
CYCLE_DIR="${CYCLE_DIR:-}"
CYCLE_REPORT="${CYCLE_REPORT:-}"
CYCLE_ID="${CYCLE_ID:-}"
BEFORE_COMMIT="${BEFORE_COMMIT:-}"
AFTER_COMMIT="${AFTER_COMMIT:-}"
PREP_EXIT_CODE="${PREP_EXIT_CODE:-}"
HERMES_EXIT_CODE="${HERMES_EXIT_CODE:-}"
OKX_RUN_ID="${OKX_RUN_ID:-}"
LOCAL_RUN_ID="${LOCAL_RUN_ID:-}"
OKX_RUN_STATUS="${OKX_RUN_STATUS:-}"
LOCAL_RUN_STATUS="${LOCAL_RUN_STATUS:-}"

# Always write the legacy optimizer-state.json for backward compatibility.
# scan-optimizer-loop still reads this file.
jq -n \
  --arg last_cycle_at "$LAST_CYCLE_AT" \
  --arg run_invocation_id "$RUN_INVOCATION_ID" \
  --arg last_commit "$LAST_COMMIT" \
  --arg last_cycle_id "$CYCLE_ID" \
  --arg last_status "$CYCLE_STATUS" \
  --arg last_cycle_dir "$CYCLE_DIR" \
  --arg last_report "$CYCLE_REPORT" \
  --arg before_commit "$BEFORE_COMMIT" \
  --arg after_commit "$AFTER_COMMIT" \
  --arg prep_exit_code "$PREP_EXIT_CODE" \
  --arg hermes_exit_code "$HERMES_EXIT_CODE" \
  --arg okx_run_id "$OKX_RUN_ID" \
  --arg local_run_id "$LOCAL_RUN_ID" \
  --arg okx_run_status "$OKX_RUN_STATUS" \
  --arg local_run_status "$LOCAL_RUN_STATUS" \
  '{
    last_cycle_at: $last_cycle_at,
    run_invocation_id: $run_invocation_id,
    last_commit: $last_commit,
    last_cycle_id: $last_cycle_id,
    last_status: $last_status,
    last_cycle_dir: $last_cycle_dir,
    last_report: $last_report,
    before_commit: $before_commit,
    after_commit: $after_commit,
    prep_exit_code: $prep_exit_code,
    hermes_exit_code: $hermes_exit_code,
    okx_run_id: $okx_run_id,
    local_run_id: $local_run_id,
    okx_run_status: $okx_run_status,
    local_run_status: $local_run_status
  }' > "$STATE_DIR/optimizer-state.json"

# ---------------------------------------------------------------------------
# Auditor-specific state — written when skill is redteam-auditor-hermes
# ---------------------------------------------------------------------------

ACTIVE_SKILL="${HERMES_SKILL:-${HERMES_SKILL:-}}"

if [[ "$ACTIVE_SKILL" == "redteam-auditor-hermes" ]]; then
    AUDIT_DIR="$ROOT_DIR/audit-reports/${CYCLE_ID:-}"
    AUDITOR_STATE_PATH="$STATE_DIR/auditor-state.json"
    EXIT_STATUS="${AUDITOR_EXIT_STATUS:-${CYCLE_STATUS:-unknown}}"
    LAST_REPORT_AUDITOR="${CYCLE_REPORT:-}"
    BASELINE_SHA="${BEFORE_COMMIT:-}"
    FINAL_SHA="${AFTER_COMMIT:-}"

    BEFORE_PATH="$AUDIT_DIR/findings-before.json"
    AFTER_PATH="$AUDIT_DIR/findings-after.json"
    [[ -f "$BEFORE_PATH" ]] || BEFORE_PATH=""
    [[ -f "$AFTER_PATH" ]]  || AFTER_PATH=""

    # Derive counters + summaries directly from findings-after.json rather than
    # requiring the agent to export AUDITOR_* env vars back to us. This also
    # lets us preserve any richer state the agent has already written into
    # auditor-state.json (notes, commits_this_cycle, etc.) instead of
    # clobbering it with env defaults.
    python3 - <<PYEOF
import json
import sys
from pathlib import Path

AUDIT_DIR = Path("$AUDIT_DIR") if "$AUDIT_DIR" else None
before_path = Path("$BEFORE_PATH") if "$BEFORE_PATH" else None
after_path = Path("$AFTER_PATH") if "$AFTER_PATH" else None
state_path = Path("$AUDITOR_STATE_PATH")

def load_json(path):
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

def summary_of(doc):
    if not doc:
        return {"by_category": {}, "by_severity": {}}
    findings = (doc.get("findings") or []) + (doc.get("deferred") or [])
    by_cat, by_sev = {}, {}
    for f in findings:
        cat = f.get("category") or "unknown"
        sev = f.get("severity") or "low"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1
    return {"by_category": by_cat, "by_severity": by_sev}

before_doc = load_json(before_path)
after_doc  = load_json(after_path)

# Derive counts from the authoritative final findings file.
fixed_count = 0
skipped_count = 0
reclassified_count = 0
if after_doc:
    for f in (after_doc.get("findings") or []) + (after_doc.get("deferred") or []):
        st = (f.get("status") or "").lower()
        if st == "fixed":
            fixed_count += 1
        elif st == "deferred" or st == "skipped":
            skipped_count += 1
        elif st == "reclassified":
            reclassified_count += 1

# Commits this cycle = BEFORE_COMMIT..FINAL_SHA (exclusive / inclusive).
import subprocess
baseline = "$BASELINE_SHA"
final    = "$FINAL_SHA"
commits = []
if baseline and final and baseline != final:
    try:
        out = subprocess.check_output(
            ["git", "-C", "${REPO_ROOT:-$ROOT_DIR/..}", "log", "--format=%H",
             f"{baseline}..{final}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        commits = [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        commits = []

# Preserve existing fields Hermes may have written (notes, custom metadata).
preserved = {}
if state_path.exists():
    try:
        preserved = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        preserved = {}
# Drop fields we're about to recompute so our values win.
for k in ("findings_before", "findings_after", "fixed_count", "regression_count",
          "skipped_count", "reclassified_count", "commits_this_cycle",
          "exit_status", "completed_at", "baseline_sha", "final_sha",
          "last_cycle_id", "last_report", "run_invocation_id"):
    preserved.pop(k, None)

result = {
    "run_invocation_id": "$RUN_INVOCATION_ID",
    "last_cycle_id": "$CYCLE_ID",
    "last_report": "$LAST_REPORT_AUDITOR",
    "baseline_sha": baseline,
    "final_sha": final,
    "findings_before": summary_of(before_doc),
    "findings_after": summary_of(after_doc),
    "fixed_count": fixed_count,
    "regression_count": int("${AUDITOR_REGRESSION_COUNT:-0}"),
    "skipped_count": skipped_count,
    "reclassified_count": reclassified_count,
    "commits_this_cycle": commits,
    "exit_status": "$EXIT_STATUS",
    "completed_at": "$LAST_CYCLE_AT",
}

# Merge preserved under the recomputed keys (preserved keys never override).
result.update({k: v for k, v in preserved.items() if k not in result})

state_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
PYEOF
fi
