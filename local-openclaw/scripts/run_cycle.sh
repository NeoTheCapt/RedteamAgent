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
  local api_src="$ROOT_DIR/audit-reports/$cycle_id/api.json"
  local logs_src="$ROOT_DIR/audit-reports/$cycle_id/logs.json"
  local feat_src="$ROOT_DIR/audit-reports/$cycle_id/features.json"
  local review_src="$ROOT_DIR/audit-reports/$cycle_id/review.md"
  local source_status="$ROOT_DIR/audit-reports/$cycle_id/source-status.json"
  local bench_hist="$STATE_DIR/benchmark-metrics-history.json"
  if [[ ! -f "$before" && ! -f "$after" ]]; then
    return 0
  fi

  python3 - \
      "$before" "$after" "$api_src" "$logs_src" "$feat_src" "$bench_hist" \
      "$cycle_id" "${OPENCLAW_TARGET_LOCAL:-}" "$review_src" \
      "${before_commit:-}" "${after_commit:-}" "$source_status" \
      "$REPO_ROOT" <<'PY'
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
REVERIFY_SCOPE_LABEL = {
    "static_live":                "已静态验证",
    "static_test":                "已单测覆盖",
    "pending_restart":            "待后端重启",
    "pending_new_run":            "待新运行",
    "runtime_restart_passed":     "重启后通过",
    "runtime_restart_still_failing": "重启后仍失败",
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
api_doc    = load(sys.argv[3])
logs_doc   = load(sys.argv[4])
feat_doc   = load(sys.argv[5])
bench_doc  = load(sys.argv[6])
this_cycle = sys.argv[7]
local_target = sys.argv[8] if len(sys.argv) > 8 else ""
review_path = sys.argv[9] if len(sys.argv) > 9 else ""
before_sha  = sys.argv[10] if len(sys.argv) > 10 else ""
after_sha   = sys.argv[11] if len(sys.argv) > 11 else ""
source_status_path = sys.argv[12] if len(sys.argv) > 12 else ""
source_status_doc = load(source_status_path) if source_status_path else None
repo_root = sys.argv[13] if len(sys.argv) > 13 else ""

import re
import subprocess

lines = []

STATUS_ZH = {
    "clean":       "已完成，0 发现",
    "found":       None,  # rendered as count below
    "unavailable": "未执行",
    "skipped":     "主动跳过",
    "error":       "执行失败",
    "not_run":     "未执行（中断）",
}
AGENT_LABEL = {"agent_bug": "agent_bug", "agent_recall": "agent_recall"}
RESULT_ZH = {
    "passed":      "通过",
    "failed":      "失败",
    "unavailable": "前置缺失",
    "skipped":     "主动跳过",
    "error":       "执行错误",
}

# Count findings per category from the authoritative doc.
agent_counts = {"agent_bug": 0, "agent_recall": 0, "orch_ui": 0}
src_for_count = after_doc or before_doc
if src_for_count:
    for f in (src_for_count.get("findings") or []) + (src_for_count.get("deferred") or []):
        cat = f.get("category")
        if cat in agent_counts:
            agent_counts[cat] += 1

# ── Phase 1 · 发现 ───────────────────────────────────────────
phase1 = ["── Phase 1 · 发现 ──"]

# prep row: API 22/22 ✓   日志 1/1 ✓   特性 10/10 ✓
prep_cells = []
for label, doc in (("API", api_doc), ("日志", logs_doc), ("特性", feat_doc)):
    if doc is None:
        prep_cells.append(f"{label} 未执行")
        continue
    pc = doc.get("pass_count") or 0
    fc = doc.get("fail_count") or 0
    total = pc + fc
    mark = "✓" if fc == 0 and total > 0 else ("✗" if fc > 0 else "?")
    prep_cells.append(f"{label} {pc}/{total} {mark}")
phase1.append("prep:  " + "   ".join(prep_cells))

# agent row: agent_bug=2  agent_recall=1
agent_cells = []
for k in ("agent_bug", "agent_recall"):
    entry = source_status_doc.get(k) if isinstance(source_status_doc, dict) else None
    if isinstance(entry, dict):
        st = (entry.get("status") or "").lower()
        count = entry.get("count")
        if st == "found":
            n = count if isinstance(count, int) else agent_counts[k]
            agent_cells.append(f"{AGENT_LABEL[k]}={n}")
        elif st == "clean":
            agent_cells.append(f"{AGENT_LABEL[k]}=0")
        else:
            zh = STATUS_ZH.get(st, st or "?")
            agent_cells.append(f"{AGENT_LABEL[k]}[{zh}]")
    else:
        agent_cells.append(f"{AGENT_LABEL[k]}={agent_counts[k]}")
phase1.append("agent: " + "  ".join(agent_cells))

# UI row: collapsed when everything passed; expanded when there are failures.
ui_entry = source_status_doc.get("orch_ui") if isinstance(source_status_doc, dict) else None
ui_checks = (ui_entry.get("checks") if isinstance(ui_entry, dict) else None) or []
if not ui_checks:
    phase1.append("UI:    未记录 per-check 状态")
else:
    total = len(ui_checks)
    passed = [c for c in ui_checks if (c.get("result") or "").lower() == "passed"]
    skipped = [c for c in ui_checks if (c.get("result") or "").lower() in ("skipped", "unavailable")]
    failing = [c for c in ui_checks if (c.get("result") or "").lower() in ("failed", "error")]
    if not failing:
        suffix = ""
        if skipped:
            # Name the skipped check(s) inline — one line stays cheap.
            names = ", ".join(str(c.get("check_id") or "?") for c in skipped[:3])
            suffix = f"（{len(skipped)} 主动跳过: {names}{'…' if len(skipped)>3 else ''}）"
        phase1.append(f"UI:    {len(passed)}/{total} 通过{suffix}")
    else:
        phase1.append(f"UI:    {len(passed)}/{total} 通过  失败 {len(failing)}:")
        for c in failing:
            cid = c.get("check_id", "?")
            name = c.get("name", "(未命名)")
            res_zh = RESULT_ZH.get((c.get("result") or "").lower(), c.get("result") or "?")
            note = str(c.get("notes") or "").strip()
            if len(note) > 80:
                note = note[:80].rstrip() + "…"
            note_part = f"（{note}）" if note else ""
            phase1.append(f"  - {cid} {name}: {res_zh}{note_part}")

# recall: 当前 / 峰值 / Δ — pulled from benchmark-metrics-history.json, which
# benchmark_gate.py now stores with a sticky `peak` field so all cycles see
# the same authoritative peak (prior behavior let Hermes scrape peak from
# ephemeral scan-optimizer docs, yielding 4 different peak values for the
# same target across 8 cycles).
if isinstance(bench_doc, dict):
    tgt = (bench_doc.get("targets") or {}).get(local_target) if local_target else None
    if not tgt:
        # Fall back to the first target if OPENCLAW_TARGET_LOCAL wasn't set.
        tgts = bench_doc.get("targets") or {}
        tgt = next(iter(tgts.values()), None) if tgts else None
    if isinstance(tgt, dict):
        last = tgt.get("last_metrics") or {}
        peak = tgt.get("peak") or {}
        def _num(s, kind=float):
            try: return kind(s)
            except (TypeError, ValueError): return None
        cur_recall = _num(last.get("challenge_recall"))
        cur_solved = _num(last.get("solved_challenges"), int)
        cur_total  = _num(last.get("total_challenges"), int)
        peak_metrics = peak.get("metrics") or {}
        pk_recall = _num(peak_metrics.get("challenge_recall"))
        pk_solved = _num(peak_metrics.get("solved_challenges"), int)
        pk_total  = _num(peak_metrics.get("total_challenges"), int)
        if cur_recall is not None or pk_recall is not None:
            parts = []
            if cur_recall is not None and cur_solved is not None and cur_total is not None:
                parts.append(f"当前 {cur_solved}/{cur_total} ({cur_recall:.3f})")
            elif cur_recall is not None:
                parts.append(f"当前 {cur_recall:.3f}")
            if pk_recall is not None and pk_solved is not None and pk_total is not None:
                pcyc = peak.get("cycle_id") or "?"
                parts.append(f"峰值 {pk_solved}/{pk_total} ({pk_recall:.3f}) @ {pcyc[:15]}")
            elif pk_recall is not None:
                parts.append(f"峰值 {pk_recall:.3f}")
            if cur_recall is not None and pk_recall is not None:
                delta = cur_recall - pk_recall
                sign = "+" if delta >= 0 else ""
                parts.append(f"Δ {sign}{delta:.3f}")
            phase1.append("recall: " + "   ".join(parts))

# 汇总: N 项（高×1, 中×2; Agent bug×2, Agent 召回×1）
def _discovery_count(doc):
    if not doc:
        return -1
    return len(doc.get("findings") or []) + len(doc.get("deferred") or [])

discovery_source = before_doc
if _discovery_count(after_doc) > _discovery_count(before_doc):
    discovery_source = after_doc
if discovery_source:
    raw_findings = list(discovery_source.get("findings") or []) + list(discovery_source.get("deferred") or [])
    seen: dict[str, dict] = {}
    findings: list[dict] = []
    for f in raw_findings:
        fid = f.get("id")
        if fid and fid in seen:
            existing = seen[fid]
            if len((f.get("summary") or "").strip()) > len((existing.get("summary") or "").strip()):
                findings[findings.index(existing)] = f
                seen[fid] = f
            continue
        if fid:
            seen[fid] = f
        findings.append(f)
    total = len(findings)
    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in findings:
        by_cat[f.get("category") or "unknown"] = by_cat.get(f.get("category") or "unknown", 0) + 1
        by_sev[f.get("severity") or "low"] = by_sev.get(f.get("severity") or "low", 0) + 1
    sev_parts = [f"{SEVERITY_LABEL[k]}×{by_sev[k]}" for k in ("critical", "high", "medium", "low") if k in by_sev]
    cat_parts = [f"{CATEGORY_LABEL.get(k, k)}×{by_cat[k]}" for k, _ in sorted(by_cat.items(), key=lambda kv: -kv[1])]
    summary_pieces = []
    if sev_parts:
        summary_pieces.append(", ".join(sev_parts))
    if cat_parts:
        summary_pieces.append("; ".join(cat_parts))
    tail = ("（" + " | ".join(summary_pieces) + "）") if summary_pieces else ""
    phase1.append(f"汇总:  {total} 项{tail}")

lines.append("\n".join(phase1))

# ── Phase 2 · 修复 ───────────────────────────────────────────
final = after_doc or before_doc
buckets: dict[str, list[dict]] = {"fixed": [], "deferred": [], "reclassified": [], "open": []}
if final:
    raw = list(final.get("findings") or []) + list(final.get("deferred") or [])
    dedup: dict[str, dict] = {}
    for f in raw:
        fid = f.get("id")
        if not fid:
            continue
        existing = dedup.get(fid)
        if existing is None:
            dedup[fid] = f
            continue
        def _score(rec: dict) -> int:
            s = rec.get("status")
            sm = rec.get("summary")
            score = 0
            if s and s not in ("open", ""):
                score += 2
            if sm and str(sm).strip():
                score += 2
            if rec.get("evidence"):
                score += 1
            return score
        if _score(f) > _score(existing):
            dedup[fid] = f
    for f in dedup.values():
        status = f.get("status") or "open"
        buckets.setdefault(status, []).append(f)

phase2 = ["── Phase 2 · 修复 ──"]

def _render_finding(f: dict, show_scope: bool) -> str:
    fid = f.get("id", "?")
    summary = (f.get("summary") or "").strip() or "(无摘要)"
    reason = (f.get("reason") or "").strip()
    parts = []
    if show_scope:
        scope = (f.get("reverify_scope") or "").strip()
        lbl = REVERIFY_SCOPE_LABEL.get(scope)
        if lbl:
            parts.append(f"[{lbl}]")
    if reason:
        # Trim long reasons so bullets stay one line each.
        if len(reason) > 140:
            reason = reason[:140].rstrip() + "…"
        parts.append(f"（{reason}）")
    suffix = (" " + " ".join(parts)) if parts else ""
    return f"  {fid}  {summary}{suffix}"

had_any = False
for key, header in (
    ("fixed", "已修复"),
    ("reclassified", "重新分类"),
    ("deferred", "延后"),
    ("open", "仍未修复"),
):
    items = buckets.get(key) or []
    if not items:
        continue
    had_any = True
    phase2.append(f"{header} ({len(items)}):")
    for f in items:
        phase2.append(_render_finding(f, show_scope=(key == "fixed")))
if not had_any:
    phase2.append("  本周期无待处理 finding")
lines.append("\n".join(phase2))

# ── Phase 3 · 复验 ───────────────────────────────────────────
phase3 = ["── Phase 3 · 复验 ──"]
if final:
    rerun_parts = []
    pc2 = final.get("pass_count")
    fc2 = final.get("fail_count")
    if isinstance(pc2, int) or isinstance(fc2, int):
        rerun_parts.append(f"pass={pc2 or 0} fail={fc2 or 0}")
    fc3 = final.get("findings_fixed")
    rc3 = final.get("regression_count")
    if fc3 is not None:
        rerun_parts.append(f"fixed={fc3}")
    if rc3 is not None:
        rerun_parts.append(f"regressions={rc3}")

    scope_counts: dict[str, int] = {}
    for f in buckets.get("fixed") or []:
        scope = (f.get("reverify_scope") or "").strip()
        if scope:
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
    scope_parts = [
        f"{REVERIFY_SCOPE_LABEL[k]}×{scope_counts[k]}"
        for k in ("static_live", "static_test",
                  "pending_restart", "runtime_restart_passed", "runtime_restart_still_failing",
                  "pending_new_run")
        if scope_counts.get(k)
    ]

    if rerun_parts:
        phase3.append("prep rerun: " + ", ".join(rerun_parts))
    if scope_parts:
        phase3.append("范围:  " + "   ".join(scope_parts))
    if len(phase3) == 1:
        phase3.append("无复验数据")
else:
    phase3.append("无复验数据")
lines.append("\n".join(phase3))

# ── Phase 4 · 代码审查 ──────────────────────────────────────
phase4 = ["── Phase 4 · 代码审查 ──"]
has_new_commits = bool(before_sha and after_sha and before_sha != after_sha)
diff_range = f"{before_sha[:7]}..{after_sha[:7]}" if before_sha and after_sha else "(未知)"
review_file = Path(review_path) if review_path else None
review_body = review_file.read_text(encoding="utf-8", errors="replace").strip() if (review_file and review_file.exists()) else ""

_GIT_CWD = repo_root or "."

def _commits_in_range(base: str, head: str) -> list[tuple[str, str]]:
    if not base or not head or base == head:
        return []
    out = subprocess.run(
        ["git", "log", "--format=%h  %s", f"{base}..{head}"],
        cwd=_GIT_CWD, text=True, capture_output=True,
    )
    if out.returncode != 0:
        return []
    result = []
    for line in out.stdout.splitlines():
        sha, _, subject = line.partition("  ")
        if sha:
            result.append((sha, subject))
    return result

def _changed_files(base: str, head: str) -> list[str]:
    if not base or not head or base == head:
        return []
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}"],
        cwd=_GIT_CWD, text=True, capture_output=True,
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()] if out.returncode == 0 else []

def _distill_review(body: str) -> list[str]:
    """Pull a tight bullet list out of review.md.

    Preference order:
      1. bullets under a `## Review conclusions` (or Chinese equivalent) heading
      2. any short bullet list at the top of the file
      3. empty — caller falls back to truncated body
    """
    if not body:
        return []
    lines_ = body.splitlines()
    target_headings = ("## review conclusions", "## 审查结论", "## conclusions", "## 审查结果")
    start_idx = None
    for i, ln in enumerate(lines_):
        low = ln.strip().lower()
        if any(low == h for h in target_headings):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    bullets = []
    for ln in lines_[start_idx:]:
        stripped = ln.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            break
        if stripped.startswith(("- ", "* ")):
            text = stripped[2:].strip()
            if len(text) > 140:
                text = text[:140].rstrip() + "…"
            bullets.append(text)
        elif stripped and bullets:
            # Continuation line of the last bullet; skip to keep output tight.
            pass
    return bullets

if not has_new_commits:
    phase4.append(f"本周期无新提交，无需审查（baseline {before_sha[:7] if before_sha else '?'} == HEAD）")
else:
    commits = _commits_in_range(before_sha, after_sha)
    changed = _changed_files(before_sha, after_sha)
    phase4.append(f"范围: {diff_range}（{len(changed)} 个文件）")
    if commits:
        phase4.append("")
        phase4.append("Commits:")
        for sha, subject in commits:
            if len(subject) > 100:
                subject = subject[:100].rstrip() + "…"
            phase4.append(f"  {sha}  {subject}")
    if review_body:
        distilled = _distill_review(review_body)
        phase4.append("")
        phase4.append("结论:")
        if distilled:
            for b in distilled:
                phase4.append(f"  ✓ {b}")
        else:
            # No structured conclusions block; show a short truncation so the
            # operator at least sees the top of the review rather than nothing.
            MAX_LEN = 600
            body_head = review_body if len(review_body) <= MAX_LEN else review_body[:MAX_LEN].rstrip() + "\n…（已截断；完整内容见 review.md）"
            for ln in body_head.splitlines()[:14]:
                phase4.append(f"  {ln}")
    else:
        phase4.append("")
        phase4.append("结论: review.md 未生成（Phase 4 可能被超时或错误中断）")

lines.append("\n".join(phase4))

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

  # Promote the auditor's explicit exit_status into the cycle-level status
  # shown at the top of the Discord summary, so `ok_no_fixes` (a legitimate
  # "codebase is clean" outcome) visually differs from a cosmetic-commit
  # `success`. Only override when the auditor skill was the one running.
  local display_status="$cycle_status"
  if [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]]; then
    local auditor_exit
    auditor_exit="$(python3 -c "
import json, pathlib
p = pathlib.Path('$STATE_DIR/auditor-state.json')
if p.exists():
    try: print(json.loads(p.read_text()).get('exit_status',''))
    except: pass
" 2>/dev/null || true)"
    if [[ "$auditor_exit" == "ok_no_fixes" ]]; then
      display_status="success_no_fixes"
    fi
  fi

  # Infrastructure-down short-circuit body. Before this, a Docker-down
  # cycle went silent (Hermes never ran, so extract_auditor_sections
  # returned nothing, fallback was the blanket "未产出可解析的阶段性结果"
  # line which tells the operator nothing about WHY). Now the summary
  # calls out the infrastructure failure directly so recovery isn't gated
  # on the operator digging through logs.
  if [[ "$cycle_status" == "skipped_infrastructure_down" ]]; then
    body=$(cat <<'INFRA'
基础设施告警: Docker daemon 不可达

本周期在前置检查阶段被中断 —— 未启动 Hermes 会话。
影响：
- 无法创建/恢复 orchestrator run
- 所有依赖容器的审计源（agent_bug 引擎内日志、UI 检查、recall benchmark）此轮无数据
- F2 / F4 / revert-evidence 校验此轮不运行

立即检查：
1. OrbStack 是否启动：orbctl status
2. Docker socket 存在：ls /Users/cis/.orbstack/run/docker.sock
3. 磁盘是否塞满：docker system df，df -h /
4. 恢复后 launchd 下一轮（30min）会自动继续
INFRA
)
  fi

  if [[ -z "$body" ]] && [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]]; then
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

状态: $display_status
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
elif ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  # Infrastructure gate. Without Docker, the orchestrator cannot start
  # containers, new runs cannot be created, and agent engagements cannot
  # run. Five consecutive cycles on 2026-04-24 (11:05Z–14:25Z) all exited
  # with `ok_no_fixes` despite OrbStack being stopped; auditor judged
  # the empty UI + zero runs as "clean cycle" while the real story was
  # total infrastructure outage. Short-circuit here so the operator
  # sees a clear `skipped_infrastructure_down` signal in Discord instead
  # of silent fake-green.
  cycle_status="skipped_infrastructure_down"
  log "docker daemon unreachable; skipping entire cycle (no Hermes session)"
  docker_err="$(docker info 2>&1 | head -3 || true)"
  if [[ -n "$docker_err" ]]; then
    log "docker error: $docker_err"
  fi
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

      # Auditor may legitimately finish with no commits when everything is
      # clean. It writes exit_status=ok_no_fixes to auditor-state.json in
      # that case. Treat that as success (no commit expected) instead of
      # the "failed_no_fix_commit" status used for real stuck-cycles.
      #
      # Hermes contract violation pattern observed across 6/12 cycles
      # 2026-04-24..2026-04-25: Hermes finished, classified everything
      # as reclassified/deferred, and never set exit_status — controller
      # rendered red `failed_no_fix_commit`. Recover from that by also
      # inferring ok_no_fixes when findings-after.json has zero `open`
      # AND zero `fixed` findings (i.e. nothing actionable, nothing
      # claimed-fixed); a commit would be wrong in that case.
      if [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]]; then
        _auditor_exit="$(python3 -c "
import json, pathlib
p = pathlib.Path('$STATE_DIR/auditor-state.json')
if p.exists():
    try: print(json.loads(p.read_text()).get('exit_status',''))
    except: pass
" 2>/dev/null || true)"
        if [[ "$_auditor_exit" == "ok_no_fixes" ]]; then
          log "auditor reported exit_status=ok_no_fixes; codebase clean, no commit expected"
          break
        fi
        # Inference fallback: every finding is reclassified or deferred → no work.
        _all_inactive="$(python3 -c "
import json, pathlib
p = pathlib.Path('$ROOT_DIR/audit-reports/$cycle_id/findings-after.json')
if not p.exists():
    print('no_file'); raise SystemExit
try:
    d = json.loads(p.read_text())
except Exception:
    print('parse_err'); raise SystemExit
records = list(d.get('findings') or []) + list(d.get('deferred') or [])
if not records:
    print('empty'); raise SystemExit
for f in records:
    s = (f.get('status') or 'open').lower()
    if s in ('open','fixed'):
        print('has_actionable'); raise SystemExit
print('all_inactive')
" 2>/dev/null || echo unknown)"
        if [[ "$_all_inactive" == "all_inactive" ]]; then
          log "auditor missed exit_status but findings-after.json has zero open/fixed findings; inferring ok_no_fixes"
          # Also stamp the global state so the Discord summary's display_status
          # logic honors it (treats as success_no_fixes, not failure).
          python3 -c "
import json, pathlib
p = pathlib.Path('$STATE_DIR/auditor-state.json')
try:
    d = json.loads(p.read_text())
except Exception:
    d = {}
d['exit_status'] = 'ok_no_fixes'
d['_inferred_by'] = 'controller_no_actionable_findings'
p.write_text(json.dumps(d, indent=2) + '\n', encoding='utf-8')
" 2>/dev/null || true
          break
        fi
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

# Bounded backend runtime re-verify — only when THIS cycle touched
# orchestrator/backend/**/*.py and at least one finding is tagged
# `reverify_scope: pending_restart`. The running uvicorn holds stale
# bytecode after a Phase 2 backend fix; without a restart the three
# prep scripts are re-reading the OLD in-memory code and a passing
# result means nothing. We do the restart once here (roughly 2s API
# downtime), rerun the prep scripts under `<cycle_id>-reverify`, and
# flip each `pending_restart` finding to either `runtime_restart_passed`
# or `runtime_restart_still_failing` (reopening the latter so the next
# cycle picks it up with elevated severity).
if [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]] \
   && [[ -n "${new_commit:-}" ]] \
   && { [[ "$cycle_status" == "success" ]] || [[ "$cycle_status" == "success_with_openclaw_error" ]]; } \
   && [[ -f "$cycle_dir/findings-after.json" ]]; then

  backend_touched="$(git -C "$REPO_ROOT" diff --name-only \
      "${before_commit}".."${after_commit}" 2>/dev/null \
      | grep -E '^orchestrator/backend/.*\.py$' | head -1 || true)"

  pending_restart_count="$(python3 - "$cycle_dir/findings-after.json" <<'PY' 2>/dev/null || echo 0
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print(0); sys.exit(0)
n = sum(
    1
    for f in (d.get("findings") or []) + (d.get("deferred") or [])
    if isinstance(f, dict) and (f.get("reverify_scope") or "") == "pending_restart"
)
print(n)
PY
)"

  if [[ -n "$backend_touched" ]] && [[ "${pending_restart_count:-0}" -gt 0 ]]; then
    log "bounded backend reverify: backend touched ($backend_touched) and $pending_restart_count pending_restart finding(s); restarting uvicorn"

    reverify_log="$cycle_dir/bounded-reverify.log"
    : > "$reverify_log"

    set +e
    bash "$REPO_ROOT/orchestrator/stop.sh" >>"$reverify_log" 2>&1
    bash "$REPO_ROOT/orchestrator/run.sh" >>"$reverify_log" 2>&1
    set -e

    # Poll healthz up to 20s before running the prep scripts; if it never
    # comes back 2xx we skip the flip entirely (safer than flipping on
    # bogus data).
    healthy=0
    for _i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      if curl -fsS --max-time 3 http://127.0.0.1:18000/healthz >/dev/null 2>&1; then
        healthy=1; break
      fi
      sleep 1
    done

    if [[ "$healthy" -eq 1 ]]; then
      reverify_cycle="${cycle_id}-reverify"
      set +e
      bash   "$ROOT_DIR/scripts/audit_orchestrator_api.sh"       "$reverify_cycle" >>"$reverify_log" 2>&1
      bash   "$ROOT_DIR/scripts/audit_orchestrator_logs.sh"      "$reverify_cycle" >>"$reverify_log" 2>&1
      python3 "$ROOT_DIR/scripts/audit_orchestrator_features.py" "$reverify_cycle" >>"$reverify_log" 2>&1
      python3 "$ROOT_DIR/scripts/apply_backend_reverify.py" \
          "$cycle_id" "$reverify_cycle" >>"$reverify_log" 2>&1
      flip_exit=$?
      set -e
      if [[ "$flip_exit" -eq 0 ]]; then
        log "bounded backend reverify: folded results into findings-after.json"
      else
        log "bounded backend reverify: apply_backend_reverify.py exited $flip_exit (see $reverify_log)"
      fi
    else
      log "bounded backend reverify: healthz never returned 2xx; skipping flip (see $reverify_log)"
    fi
  fi
fi

# F4 — Validate cycle artifacts before the Discord summary goes out.
# The validator is a read-only schema check over findings-after.json,
# source-status.json, and commit-message finding-id references. If it
# finds violations (duplicate ids, missing screenshots, bad fingerprints,
# commit msg references a non-existent FND-XXX, etc.) we annotate the
# cycle status so the operator sees something is dirty — but we do NOT
# abort, because the agent already produced the commits and rolling back
# now would lose useful state.
#
# F2 — Cross-cycle regression delta: flag lines that this cycle's diff
# removed when those same lines were added by recent audit commits. Catches
# the 8aed200-style "rerender wipes prior rule" case.
if [[ "${OPENCLAW_SKILL:-}" == "redteam-auditor-hermes" ]]; then
  artifact_log="$cycle_dir/artifact-validation.log"
  regression_log="$cycle_dir/cross-cycle-regression.log"

  set +e
  python3 "$ROOT_DIR/scripts/validate_cycle_artifacts.py" \
      "$cycle_id" \
      --baseline-sha "${before_commit:-}" \
      2> "$artifact_log" >/dev/null
  artifact_exit=$?

  regression_exit=0
  # Write to audit-reports dir (not logs) so validate_revert_evidence.py
  # can find it. The two dirs had diverged; cycle 20260424T160049Z was the
  # first to trip this mismatch — F2 wrote to logs/, the revert validator
  # looked in audit-reports/, and every violation slipped through.
  regression_json="$ROOT_DIR/audit-reports/$cycle_id/cross-cycle-regression.json"
  mkdir -p "$(dirname "$regression_json")"
  if [[ -n "${before_commit:-}" ]]; then
    python3 "$ROOT_DIR/scripts/check_regression_against_prior_cycles.py" \
        "$before_commit" \
        --lookback 30 \
        --json-out "$regression_json" \
        2> "$regression_log" >/dev/null
    regression_exit=$?
  fi

  # Revert cooling-off validator: when the cycle diff deletes lines that a
  # prior `fix(audit-*)` commit added, every fixed finding in the cycle must
  # carry concrete `evidence.regression_evidence` (recall drop cycle id,
  # failing test output, log path:line, or cases.db outcome). Prose-only
  # justifications in review.md's ## Cross-cycle deletions section are
  # acknowledged but not sufficient — they allowed four consecutive flip-
  # flops between parallel/serialized dispatch rules inside 21h.
  revert_log="$cycle_dir/revert-evidence.log"
  revert_exit=0
  if [[ -n "${before_commit:-}" ]] && [[ -f "$regression_json" ]]; then
    python3 "$ROOT_DIR/scripts/validate_revert_evidence.py" \
        "$cycle_id" \
        --baseline-sha "${before_commit:-}" \
        2> "$revert_log" >/dev/null
    revert_exit=$?
  fi

  # ui-07 must NOT stop a run targeting okx.com — observed across 7
  # consecutive cycles (054522Z..111827Z) where ui-07 stopped okx runs
  # #678..#709 and the okx target was effectively never running. Skill
  # rule was added but Hermes may cache stale skill text; this validator
  # is the controller-side enforcement.
  steady_state_log="$cycle_dir/steady-state-runs.log"
  steady_state_exit=0
  python3 "$ROOT_DIR/scripts/validate_steady_state_runs.py" "$cycle_id" \
      2> "$steady_state_log" >/dev/null
  steady_state_exit=$?
  set -e

  if [[ $artifact_exit -ne 0 ]]; then
    log "artifact validation reported violations; see $artifact_log"
  else
    log "artifact validation passed"
  fi
  if [[ $regression_exit -ne 0 ]]; then
    log "cross-cycle regression check flagged deleted prior-audit lines; see $regression_log"
  fi
  if [[ $revert_exit -ne 0 ]]; then
    log "revert cooling-off: fixed findings lack concrete regression_evidence; see $revert_log"
  fi
  if [[ $steady_state_exit -ne 0 ]]; then
    log "steady-state: a fixed target has zero running runs at cycle end; see $steady_state_log"
  fi

  if [[ $artifact_exit -ne 0 || $regression_exit -ne 0 || $revert_exit -ne 0 || $steady_state_exit -ne 0 ]]; then
    if [[ "$cycle_status" == "success" || "$cycle_status" == "success_with_openclaw_error" ]]; then
      cycle_status="success_with_dirty_artifacts"
    fi
  fi
fi

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

# Post-cycle cleanup of analyzed failed runs.
#
# KEEP_TERMINAL_RUNS=1 during prep preserved failed runs' engagement dirs
# so Hermes could read log.md / run.json in Phase 1. Once the cycle finishes
# with status=success AND Hermes actually committed a fix derived from those
# runs' evidence (new_commit set), the engagement dirs are redundant — the
# analysis is permanent in audit-reports/<cycle_id>/ + the git commit.
#
# Delete only runs whose id appears in this cycle's findings-before.json
# evidence (= Hermes saw them). If findings-before.json doesn't reference a
# failed run id, leave it — Hermes hasn't captured it yet, next cycle must
# still see it.
if [[ "$cycle_status" == "success" && -n "$new_commit" ]]; then
  audit_findings_before="$ROOT_DIR/audit-reports/$cycle_id/findings-before.json"
  if [[ -f "$audit_findings_before" ]]; then
    set +e
    analyzed_run_ids="$(python3 - "$audit_findings_before" <<'PY' 2>/dev/null
import json, re, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
ids = set()
for f in (d.get("findings") or []) + (d.get("deferred") or []):
    # Search evidence fields for numeric run IDs the finding refers to.
    ev = f.get("evidence") or {}
    blob = json.dumps(ev) + " " + (f.get("summary") or "") + " " + json.dumps(f.get("_refs") or {})
    # Common shapes we emit: "run.id": 482, "run_id": 482, "run-0482", "/runs/482"
    for m in re.findall(r"(?:run[_-]?id\D{0,4}|runs?[\/-])(\d+)", blob):
        ids.add(int(m))
    # Also pick up bare integers labelled 'id' when evidence has a run dict
    if isinstance(ev, dict):
        rid = ev.get("run_id") or (ev.get("run") or {}).get("id") if isinstance(ev.get("run"), dict) else None
        if isinstance(rid, int):
            ids.add(rid)
print(" ".join(str(i) for i in sorted(ids)))
PY
)"
    set -e

    if [[ -n "$analyzed_run_ids" ]]; then
      # Only delete runs whose CURRENT orchestrator status is terminal — if a
      # referenced run is somehow still running/queued, leave it alone.
      token="${ORCH_TOKEN:-}"
      if [[ -z "$token" ]]; then
        token="$(grep -m1 '^ORCH_TOKEN=' "$STATE_DIR/scheduler.env" 2>/dev/null | cut -d= -f2- || true)"
      fi
      if [[ -n "$token" ]]; then
        for rid in $analyzed_run_ids; do
          status_json="$(curl -sS --max-time 5 -H "Authorization: Bearer $token" \
              "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" 2>/dev/null || echo '[]')"
          rstatus="$(printf '%s' "$status_json" | jq -r --arg rid "$rid" '[.[] | select(.id == ($rid|tonumber))] | .[0].status // empty' 2>/dev/null)"
          case "$rstatus" in
            failed|failure|error|errored|stopped|cancelled|canceled|timeout)
              log "post-cycle: deleting analyzed failed run $rid (status=$rstatus; evidence captured in audit-reports/$cycle_id/)"
              curl -sS --max-time 5 -X DELETE -H "Authorization: Bearer $token" \
                  "$ORCH_BASE_URL/projects/$PROJECT_ID/runs/$rid" >/dev/null 2>&1 || \
                  log "warning: failed to delete run $rid"
              ;;
            "")
              # Run no longer exists (already deleted) — nothing to do.
              ;;
            *)
              log "post-cycle: skipping run $rid (status=$rstatus is not terminal)"
              ;;
          esac
        done
      fi
    fi
  fi
fi

# Layer 1 disk hygiene: each cycle's `run.sh --rebuild` (when prep detects
# fixed-target drift) produces a new 7.5GB redteam-allinone image and turns
# the old one into dangling layers. Without this prune, OrbStack's disk
# filled to 160 GB of garbage over ~2 weeks and the daemon crashed, taking
# down every audit cycle with it. Prune is idempotent: only touches dangling
# layers + build cache beyond 2 GB; never removes a tagged image in use.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  pruned_images=$(docker image prune -f 2>/dev/null | awk '/Total reclaimed space/ {print}')
  pruned_cache=$(docker builder prune -f --keep-storage 2GB 2>/dev/null | awk '/Total/ {print}')
  log "docker prune: ${pruned_images:-nothing}${pruned_images:+ / }${pruned_cache:-no cache}"
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
