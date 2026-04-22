#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
LOGS_DIR="$ROOT_DIR/logs"
CYCLES_DIR="$LOGS_DIR/cycles"
LOCK_DIR="$STATE_DIR/run.lock"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/config.sh"

OPENCLAW_BIN="${OPENCLAW_BIN:-$(command -v openclaw || true)}"
# Require OPENCLAW_SKILL to be set explicitly by the caller. Silently defaulting
# to scan-optimizer-loop caused real confusion: a scheduled auditor run that
# forgot to export the var would quietly start mutating optimizer-state.json.
OPENCLAW_SKILL="${OPENCLAW_SKILL:-}"
if [[ -z "$OPENCLAW_SKILL" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] OPENCLAW_SKILL must be set (e.g. redteam-auditor-hermes or scan-optimizer-loop)" >&2
  exit 2
fi
REPORT_CHANNEL="${REPORT_CHANNEL:-}"
REPORT_TO="${REPORT_TO:-}"

mkdir -p "$STATE_DIR" "$LOGS_DIR" "$CYCLES_DIR"

iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

fs_now() {
  date -u +%Y%m%dT%H%M%SZ
}

cycle_id="$(fs_now)"
cycle_dir="$CYCLES_DIR/$cycle_id"
mkdir -p "$cycle_dir"

controller_log="$cycle_dir/controller.log"
prep_log="$cycle_dir/prep.log"
openclaw_log="$cycle_dir/openclaw.log"
final_context_log="$cycle_dir/final-context.log"
report_path="$cycle_dir/report.md"
metadata_path="$cycle_dir/metadata.json"

log() {
  printf '[%s] %s\n' "$(iso_now)" "$*" | tee -a "$controller_log"
}

extract_fixed_issues() {
  if [[ ! -f "$report_path" ]]; then
    return 0
  fi

  python3 - "$report_path" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
sections = []

# Phase 1: 确认修复的 bug
bugs = re.search(
    r"^(?:\d+\.\s+)(?:.*?(?:确认修复|confirmed\s+bugs?\s+fixed|修复的\s*bug)).*?\n(.*?)(?=^\d+\.\s+|^## |\Z)",
    text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
if bugs and bugs.group(1).strip():
    sections.append("修复的 bug:\n" + bugs.group(1).strip())

# Phase 2: 准招分析与改进
bench = re.search(
    r"^(?:\d+\.\s+)(?:.*?(?:准招分析|challenge\s+score)).*?\n(.*?)(?=^\d+\.\s+|^## |\Z)",
    text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
if bench and bench.group(1).strip():
    sections.append("准招分析:\n" + bench.group(1).strip())

# Phase 3: 代码审查与优化
review = re.search(
    r"^(?:\d+\.\s+)(?:.*?(?:代码审查|code\s+review)).*?\n(.*?)(?=^\d+\.\s+|^## |\Z)",
    text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
if review and review.group(1).strip():
    sections.append("代码审查:\n" + review.group(1).strip())

if sections:
    print("\n\n".join(sections))
PY
}

extract_auditor_sections() {
  # Build a Chinese summary for redteam-auditor-hermes cycles by reading the
  # structured findings-after.json / findings-before.json that audit_cycle_prep.sh
  # and the auditor skill produce. Falls back to an empty output if neither file
  # is present, which makes the caller fall back to the raw Openclaw tail.
  local before="$ROOT_DIR/audit-reports/$cycle_id/findings-before.json"
  local after="$ROOT_DIR/audit-reports/$cycle_id/findings-after.json"
  if [[ ! -f "$before" && ! -f "$after" ]]; then
    return 0
  fi

  python3 - "$before" "$after" <<'PY'
import json
import sys
from pathlib import Path

CATEGORY_LABEL = {
    "orch_api":     "后端 API",
    "orch_log":     "后端日志",
    "orch_feature": "后端特性",
    "orch_ui":      "前端 UI",
    "agent_bug":    "Agent bug",
    "agent_recall": "Agent 召回",
}
SEVERITY_LABEL = {
    "critical": "严重",
    "high":     "高",
    "medium":   "中",
    "low":      "低",
}
STATUS_LABEL = {
    "fixed":        "已修复",
    "deferred":     "延后",
    "reclassified": "重新分类",
    "open":         "未修复",
}

def load(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

before_doc = load(sys.argv[1])
after_doc = load(sys.argv[2])

lines = []

# --- 发现阶段：用发现项最多的那份做类别 / 严重度汇总 ---
def _discovery_count(doc):
    if not doc:
        return -1
    return len(doc.get("findings") or []) + len(doc.get("deferred") or [])

source = before_doc
if _discovery_count(after_doc) > _discovery_count(before_doc):
    source = after_doc
if source:
    findings = list(source.get("findings") or []) + list(source.get("deferred") or [])
    total = len(findings)
    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in findings:
        cat = f.get("category") or "unknown"
        sev = f.get("severity") or "low"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1

    section = [f"发现阶段（共 {total} 项）"]
    if by_cat:
        section.append("类别分布:")
        for cat, count in sorted(by_cat.items()):
            section.append(f"- {CATEGORY_LABEL.get(cat, cat)}: {count}")
    if by_sev:
        section.append("严重度分布:")
        for sev in ("critical", "high", "medium", "low"):
            if sev in by_sev:
                section.append(f"- {SEVERITY_LABEL[sev]}: {by_sev[sev]}")
    lines.append("\n".join(section))

# --- 修复 / 重新分类 / 延后阶段：优先使用 findings-after ---
final = after_doc or before_doc
if final:
    buckets: dict[str, list[dict]] = {"fixed": [], "deferred": [], "reclassified": [], "open": []}
    for f in list(final.get("findings") or []) + list(final.get("deferred") or []):
        status = f.get("status") or "open"
        buckets.setdefault(status, []).append(f)

    def render_bucket(key, header):
        items = buckets.get(key) or []
        if not items:
            return None
        body = [header]
        for f in items:
            fid = f.get("id", "?")
            summary = (f.get("summary") or "").strip() or "(无摘要)"
            reason = (f.get("reason") or "").strip()
            suffix = f"（原因：{reason}）" if reason else ""
            body.append(f"- {fid}: {summary}{suffix}")
        return "\n".join(body)

    fixed_section = render_bucket("fixed", "修复阶段:")
    if fixed_section:
        lines.append(fixed_section)
    reclassified_section = render_bucket("reclassified", "重新分类（视为非本仓库问题）:")
    if reclassified_section:
        lines.append(reclassified_section)
    deferred_section = render_bucket("deferred", "延后项:")
    if deferred_section:
        lines.append(deferred_section)
    open_section = render_bucket("open", "仍未修复:")
    if open_section:
        lines.append(open_section)

    # 复验计数（如果 findings-after 里带了）
    rerun_parts = []
    pass_count = final.get("pass_count")
    fail_count = final.get("fail_count")
    if isinstance(pass_count, int) or isinstance(fail_count, int):
        rerun_parts.append(f"pass={pass_count or 0} fail={fail_count or 0}")
    fixed_count = final.get("findings_fixed")
    regression_count = final.get("regression_count")
    if fixed_count is not None:
        rerun_parts.append(f"fixed={fixed_count}")
    if regression_count is not None:
        rerun_parts.append(f"regressions={regression_count}")
    if rerun_parts:
        lines.append("复验阶段:\n- " + ", ".join(rerun_parts))

if lines:
    print("\n\n".join(lines))
PY
}

extract_openclaw_summary_raw() {
  if [[ -f "$report_path" ]]; then
    awk '
      /^## OpenClaw Summary \(tail\)/ {in_section=1; next}
      in_section && /^```text$/ {in_code=1; next}
      in_code && /^```$/ {exit}
      in_code {print}
    ' "$report_path"
    return 0
  fi

  if [[ -f "$openclaw_log" ]]; then
    tail -n 120 "$openclaw_log"
  fi
}

_benchmark_gate() {
  python3 "$ROOT_DIR/scripts/lib/benchmark_gate.py" \
      --context-file "$STATE_DIR/latest-context.md" \
      --history-file "$STATE_DIR/benchmark-metrics-history.json" \
      --mode "$@"
}

# Only used for post-cycle history recording — all evaluation is done by OpenClaw.
update_local_benchmark_history()          { _benchmark_gate update-history --cycle-id "$cycle_id"; }

cycle_title() {
  case "${OPENCLAW_SKILL:-}" in
    redteam-auditor-hermes) echo "巡检" ;;
    *)                      echo "扫描优化" ;;
  esac
}

send_cycle_started_summary() {
  if [[ -z "$REPORT_CHANNEL" || -z "$REPORT_TO" || -z "$OPENCLAW_BIN" ]]; then
    log "start delivery skipped (REPORT_CHANNEL / REPORT_TO / OPENCLAW_BIN not fully set)"
    return 0
  fi

  local title
  title="$(cycle_title)"
  local msg_file="$cycle_dir/start-message.txt"
  cat > "$msg_file" <<EOF
${title}周期已启动

周期 ID: $cycle_id
启动时间: $start_at
调度间隔: ${LOCAL_OPENCLAW_INTERVAL_SECONDS:-900}s
观察窗口: ${OPENCLAW_OBSERVATION_SECONDS}s
目标:
- $OPENCLAW_TARGET_OKX
- $OPENCLAW_TARGET_LOCAL

日志目录: $cycle_dir
EOF

  set +e
  "$OPENCLAW_BIN" message send --channel "$REPORT_CHANNEL" --target "$REPORT_TO" --message "$(cat "$msg_file")" >> "$controller_log" 2>&1
  local delivery_status=$?
  set -e

  if [[ $delivery_status -eq 0 ]]; then
    log "start summary delivered to $REPORT_CHANNEL:$REPORT_TO"
  else
    log "start summary delivery failed with exit code $delivery_status"
  fi
}

send_cycle_summary() {
  if [[ -z "$REPORT_CHANNEL" || -z "$REPORT_TO" || -z "$OPENCLAW_BIN" ]]; then
    log "summary delivery skipped (REPORT_CHANNEL / REPORT_TO / OPENCLAW_BIN not fully set)"
    return 0
  fi

  local title
  title="$(cycle_title)"
  local body=""

  if [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]]; then
    body="$(extract_auditor_sections || true)"
  fi

  if [[ -z "$body" ]]; then
    body="$(extract_fixed_issues || true)"
  fi

  if [[ -z "$body" ]]; then
    body="$(extract_openclaw_summary_raw || true)"
  fi

  if [[ -z "$body" ]]; then
    body='(本周期未产出可解析的阶段性结果)'
  fi

  local msg_file="$cycle_dir/summary-message.txt"
  cat > "$msg_file" <<EOF
${title}周期完成

状态: $cycle_status
周期 ID: $cycle_id
尝试次数: $attempt_count
OKX 任务: ${okx_run_id:-unknown} (${okx_run_status:-unknown})
本地任务: ${local_run_id:-unknown} (${local_run_status:-unknown})
新提交: ${new_commit:-none}

$body

报告: $report_path
EOF

  set +e
  "$OPENCLAW_BIN" message send --channel "$REPORT_CHANNEL" --target "$REPORT_TO" --message "$(cat "$msg_file")" >> "$controller_log" 2>&1
  delivery_status=$?
  set -e

  if [[ $delivery_status -eq 0 ]]; then
    log "summary delivered to $REPORT_CHANNEL:$REPORT_TO"
  else
    log "summary delivery failed with exit code $delivery_status"
  fi
}

cleanup_lock() {
  rm -rf "$LOCK_DIR"
}

write_skip_report() {
  cat > "$report_path" <<EOF
# Scan Optimizer Cycle Report

## Cycle Metadata
- cycle_id: $cycle_id
- started_at: $start_at
- status: skipped_overlap
- reason: another cycle already holds the local-openclaw lock
- lock_dir: $LOCK_DIR
- controller_log: $controller_log
EOF
}

persist_cycle_state() {
  export CYCLE_STATUS="$cycle_status"
  export CYCLE_DIR="$cycle_dir"
  export CYCLE_REPORT="$report_path"
  export CYCLE_ID="$cycle_id"
  export BEFORE_COMMIT="$before_commit"
  export AFTER_COMMIT="$after_commit"
  export PREP_EXIT_CODE="$prep_status"
  export OPENCLAW_EXIT_CODE="$openclaw_status"
  export OKX_RUN_ID="$okx_run_id"
  export LOCAL_RUN_ID="$local_run_id"
  export OKX_RUN_STATUS="$okx_run_status"
  export LOCAL_RUN_STATUS="$local_run_status"
  "$ROOT_DIR/scripts/update_cycle_state.sh" "$new_commit"
}

sync_run_ids_from_json() {
  local json_file="$1"
  [[ -f "$json_file" ]] || return 0
  # Trailing-slash tolerant target matching.
  local _m='def tm($t): (.target == $t or .target == ($t + "/") or .target == ($t | rtrimstr("/")));'
  okx_run_id="$(jq -r "$_m"' [ .[] | select(tm("'"$OPENCLAW_TARGET_OKX"'")) ] | last.id // empty' "$json_file" 2>/dev/null || true)"
  local_run_id="$(jq -r "$_m"' [ .[] | select(tm("'"$OPENCLAW_TARGET_LOCAL"'")) ] | last.id // empty' "$json_file" 2>/dev/null || true)"
  okx_run_status="$(jq -r "$_m"' [ .[] | select(tm("'"$OPENCLAW_TARGET_OKX"'")) ] | last.status // empty' "$json_file" 2>/dev/null || true)"
  local_run_status="$(jq -r "$_m"' [ .[] | select(tm("'"$OPENCLAW_TARGET_LOCAL"'")) ] | last.status // empty' "$json_file" 2>/dev/null || true)"
}


start_at="$(iso_now)"
before_commit="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
after_commit="$before_commit"
new_commit=""
prep_status=0
openclaw_status=0
cycle_status="running"
openclaw_ran="false"
summary_excerpt=""
okx_run_id=""
local_run_id=""
okx_run_status=""
local_run_status=""
attempt_count=0
current_branch=""

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  # Check for stale lock: verify the holding process is still alive.
  lock_pid=""
  if [[ -f "$LOCK_DIR/pid" ]]; then
    lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  fi
  if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
    cycle_status="skipped_overlap"
    log "another cycle (pid=$lock_pid) is already running; skipping"
    write_skip_report
    persist_cycle_state
    exit 0
  fi
  # Holding process is gone — stale lock. Reclaim it.
  log "stale lock detected (pid=${lock_pid:-unknown} not running); reclaiming"
  rm -rf "$LOCK_DIR"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    cycle_status="skipped_overlap"
    log "failed to reclaim lock; skipping"
    write_skip_report
    persist_cycle_state
    exit 0
  fi
fi
trap cleanup_lock EXIT

echo "$cycle_id" > "$LOCK_DIR/cycle_id"
echo "$$" > "$LOCK_DIR/pid"
echo "$start_at" > "$LOCK_DIR/started_at"

persist_cycle_state

log "cycle started in $cycle_dir"
log "repo root: $REPO_ROOT"
log "openclaw binary: ${OPENCLAW_BIN:-missing}"
log "skill: $OPENCLAW_SKILL"
send_cycle_started_summary

tree_is_dirty() {
  ! git -C "$REPO_ROOT" diff --quiet 2>/dev/null ||
  ! git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null
}

if [[ -z "$OPENCLAW_BIN" ]]; then
  cycle_status="failed_preflight"
  log "openclaw binary not found in PATH"
elif [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" \
        && "${ALLOW_DIRTY_TREE:-0}" != "1" ]] && tree_is_dirty; then
  # Auditor isolation: refuse to start against a dirty working tree. Without
  # this guard the agent inherits unstaged/staged human edits, runs tests
  # against them, and commits them as its own work (verified in cycle
  # 20260422T025630Z: the agent's `rm -rf` for the baseline worktree was
  # sandbox-denied and it silently fell through to the dirty dev tree).
  cycle_status="skipped_dirty_tree"
  log "auditor cycle aborted: working tree is dirty"
  log "hint: commit/stash first, or set ALLOW_DIRTY_TREE=1 to override"
else
  # Skill-based prep dispatch. Auditor cycle uses audit_cycle_prep.sh which
  # only probes orchestrator API/logs/features — it does NOT create runs, so
  # it's independent of TARGET_OKX reachability or active engagements.
  case "${OPENCLAW_SKILL:-${HERMES_SKILL:-scan-optimizer-hermes}}" in
    redteam-auditor-hermes)
      prep_script="$ROOT_DIR/scripts/audit_cycle_prep.sh"
      ;;
    *)
      prep_script="$ROOT_DIR/scripts/run_cycle_prep.sh"
      ;;
  esac
  set +e
  CYCLE_ID="$cycle_id" CYCLE_LOG_DIR="$cycle_dir" "$prep_script" 2>&1 | tee "$prep_log"
  prep_status=${PIPESTATUS[0]}
  set -e

  if [[ $prep_status -ne 0 ]]; then
    cycle_status="failed_prep"
    sync_run_ids_from_json "$STATE_DIR/latest-runs.json"
    log "prep failed with exit code $prep_status"
  else
    prompt_file="$STATE_DIR/openclaw-prompt.txt"
    created_runs_json="$STATE_DIR/latest-created-runs.json"

    if [[ -f "$created_runs_json" ]]; then
      okx_run_id="$(jq -r '.okx.id // empty' "$created_runs_json" 2>/dev/null || true)"
      local_run_id="$(jq -r '.local.id // empty' "$created_runs_json" 2>/dev/null || true)"
    fi

    while true; do
      attempt_count=$((attempt_count + 1))
      # Only the legacy scan-optimizer-loop skill needs workspace-skill
      # sync into ~/.openclaw/. Auditor-on-Hermes skills live under
      # ~/.hermes/skills/ and don't rely on this legacy path.
      if [[ "${SYNC_OPENCLAW_SKILL:-1}" == "1" \
            && "${OPENCLAW_SKILL:-}" != "redteam-auditor-hermes" ]]; then
        "$ROOT_DIR/scripts/sync_openclaw_skill.sh" >> "$controller_log" 2>&1
      fi
      log "openclaw attempt #$attempt_count starting"
      openclaw_ran="true"
      prompt_text="$(cat "$prompt_file")"
      {
        echo "===== attempt $attempt_count @ $(iso_now) ====="
      } >> "$openclaw_log"

      set +e
      "$OPENCLAW_BIN" agent --session-id "local-openclaw-$cycle_id" --message "$prompt_text" --timeout "$OPENCLAW_TIMEOUT_SECONDS" 2>&1 | tee -a "$openclaw_log"
      openclaw_status=${PIPESTATUS[0]}
      set -e

      if [[ $openclaw_status -ne 0 ]]; then
        cycle_status="failed_openclaw"
        log "openclaw exited with code $openclaw_status on attempt #$attempt_count"
      else
        cycle_status="success"
      fi

      if [[ -f "$openclaw_log" ]]; then
        summary_excerpt="$(tail -n 120 "$openclaw_log")"
      fi

      # Refresh run IDs from orchestrator API, but do NOT rebuild latest-context.md.
      # Rebuilding would overwrite the prep-stage challenge score with stale/wrong data
      # if OpenClaw created new runs during Phase 1-3.
      {
        source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"
        orchestrator_curl "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$STATE_DIR/latest-runs.json"
      } 2>/dev/null || true
      sync_run_ids_from_json "$STATE_DIR/latest-runs.json"

      after_commit="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
      current_branch="$(git -C "$REPO_ROOT" symbolic-ref --short HEAD 2>/dev/null || true)"
      if [[ -n "$before_commit" && -n "$after_commit" && "$before_commit" != "$after_commit" ]]; then
        if [[ -z "$current_branch" ]]; then
          log "warning: new commit $after_commit detected but HEAD is detached"
        fi
        new_commit="$after_commit"
      fi

      # Check HEALTHY_SKIP first — OpenClaw's final verdict takes precedence.
      # It may have created a commit during Phase 1 but concluded healthy overall.
      if grep -qF "$OPENCLAW_HEALTHY_SKIP_MARKER" "$openclaw_log" 2>/dev/null; then
        if [[ -n "$new_commit" ]]; then
          log "openclaw reported healthy but also committed $new_commit; treating as success (commit takes precedence)"
          cycle_status="success"
        else
          cycle_status="skipped_healthy_runs"
          log "openclaw completed all phases with no actionable issues; skipping this cycle"
        fi
        break
      fi

      if [[ -n "$new_commit" ]]; then
        if [[ $openclaw_status -ne 0 ]]; then
          cycle_status="success_with_openclaw_error"
          log "detected new local commit $new_commit on branch ${current_branch:-DETACHED} (openclaw exited $openclaw_status); cycle can finish"
        else
          cycle_status="success"
          log "detected new local commit $new_commit on branch ${current_branch:-DETACHED}; cycle can finish"
        fi
        break
      fi

      if [[ "$cycle_status" != "success" ]]; then
        break
      fi

      cycle_status="failed_no_fix_commit"
      log "openclaw finished without a bug-fix commit and without an explicit healthy-skip marker"
      break
    done
  fi
fi

jq -n \
  --arg cycle_id "$cycle_id" \
  --arg started_at "$start_at" \
  --arg finished_at "$(iso_now)" \
  --arg status "$cycle_status" \
  --argjson attempt_count "$attempt_count" \
  --argjson prep_exit_code "$prep_status" \
  --argjson openclaw_exit_code "$openclaw_status" \
  --arg before_commit "$before_commit" \
  --arg after_commit "$after_commit" \
  --arg new_commit "$new_commit" \
  --arg okx_run_id "$okx_run_id" \
  --arg local_run_id "$local_run_id" \
  --arg okx_run_status "$okx_run_status" \
  --arg local_run_status "$local_run_status" \
  '{
    cycle_id: $cycle_id,
    started_at: $started_at,
    finished_at: $finished_at,
    status: $status,
    attempt_count: $attempt_count,
    prep_exit_code: $prep_exit_code,
    openclaw_exit_code: $openclaw_exit_code,
    before_commit: $before_commit,
    after_commit: $after_commit,
    new_commit: $new_commit,
    okx_run_id: $okx_run_id,
    local_run_id: $local_run_id,
    okx_run_status: $okx_run_status,
    local_run_status: $local_run_status
  }' > "$metadata_path"

cat > "$report_path" <<EOF
# Scan Optimizer Cycle Report

## Cycle Metadata
- cycle_id: $cycle_id
- started_at: $start_at
- finished_at: $(iso_now)
- status: $cycle_status
- attempt_count: $attempt_count
- repo_root: $REPO_ROOT
- openclaw_bin: ${OPENCLAW_BIN:-missing}
- openclaw_skill: $OPENCLAW_SKILL
- openclaw_timeout_seconds: ${OPENCLAW_TIMEOUT_SECONDS}
- schedule_interval_seconds: ${LOCAL_OPENCLAW_INTERVAL_SECONDS:-900}

## Fixed Targets
- okx: $OPENCLAW_TARGET_OKX
- local: $OPENCLAW_TARGET_LOCAL

## Tracked Run IDs
- okx_run_id: ${okx_run_id:-unknown}
- local_run_id: ${local_run_id:-unknown}

## Final Observed Run Status
- okx_run_status: ${okx_run_status:-unknown}
- local_run_status: ${local_run_status:-unknown}

## Exit Codes
- prep_exit_code: $prep_status
- openclaw_exit_code: $openclaw_status
- openclaw_ran: $openclaw_ran

## Git State
- before_commit: ${before_commit:-unknown}
- after_commit: ${after_commit:-unknown}
- new_commit: ${new_commit:-none}

## Important Files
- state_dir: $STATE_DIR
- latest_created_runs: $STATE_DIR/latest-created-runs.json
- latest_runs: $STATE_DIR/latest-runs.json
- latest_context: $STATE_DIR/latest-context.md
- prompt_file: $STATE_DIR/openclaw-prompt.txt
- optimizer_state: $STATE_DIR/optimizer-state.json

## Logs
- controller_log: $controller_log
- prep_log: $prep_log
- openclaw_log: $openclaw_log
- final_context_log: $final_context_log
- metadata_json: $metadata_path

## OpenClaw Summary (tail)
EOF

if [[ -n "$summary_excerpt" ]]; then
  {
    echo '```text'
    printf '%s\n' "$summary_excerpt"
    echo '```'
  } >> "$report_path"
else
  echo '_no openclaw output captured_' >> "$report_path"
fi

if [[ -n "$new_commit" ]]; then
  {
    echo
    echo '## Commit Summary'
    echo '```text'
    git -C "$REPO_ROOT" show --stat --oneline --no-patch "$new_commit" || true
    echo
    git -C "$REPO_ROOT" show --stat --format='' "$new_commit" || true
    echo '```'
    echo
    echo '## Changed Files'
    echo '```text'
    git -C "$REPO_ROOT" diff-tree --no-commit-id --name-only -r "$new_commit" || true
    echo '```'
  } >> "$report_path"
fi

persist_cycle_state

send_cycle_summary
update_local_benchmark_history || true

# Post-cycle Juice Shop restart — this is the ONLY place Juice Shop gets restarted.
# All other code paths (prep recovery, Phase 1-3) must NOT restart Juice Shop.
# This guarantees challenge score data is intact throughout the entire cycle.
_restart_juice_shop=false

# Only restart Juice Shop when BOTH conditions are true:
# 1. This cycle actually scored a completed run (prep wrote scored-this-cycle flag)
# 2. OpenClaw committed code changes (Phase 2 recall improvements need verification)
# This prevents restart when: run still running, Phase 1-only commits, old scored runs.
if [[ -n "$new_commit" ]] && [[ -f "$cycle_dir/scored-this-cycle" ]]; then
  log "post-cycle: code committed after scoring in this cycle; will restart Juice Shop"
  _restart_juice_shop=true
fi

if [[ "$_restart_juice_shop" == "true" ]]; then
  log "post-cycle: restarting Juice Shop and creating fresh run (last step of cycle)"
  docker restart juice-shop >/dev/null 2>&1 || log "warning: docker restart juice-shop failed"
  sleep 3
  set +e
  FORCE_REPLACE_ACTIVE_RUNS=1 TARGET_FILTER=local "$ROOT_DIR/scripts/create_runs.sh" >/dev/null 2>&1
  set -e
  # Do NOT delete or modify last-scored-run-id. It keeps the old run ID so
  # the next cycle won't re-score that same completed run. When the NEW run
  # completes, its different ID will trigger fresh scoring automatically.
fi

log "cycle finished with status=$cycle_status report=$report_path"

case "$cycle_status" in
  success|success_with_openclaw_error|skipped_healthy_runs)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
