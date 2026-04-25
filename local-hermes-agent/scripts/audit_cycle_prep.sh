#!/usr/bin/env bash
# audit_cycle_prep.sh — unified cycle prep for redteam-auditor-hermes
#
# Chains existing scan-optimizer prep (run_cycle_prep.sh) with the 3 new
# orchestrator audit scripts, then merges all findings-before.json and
# appends a unified context to latest-context.md.
#
# Usage: Called automatically by run_cycle.sh when HERMES_SKILL=redteam-auditor-hermes
#        Can also be invoked directly for testing:
#          CYCLE_ID=20260418T120000Z bash audit_cycle_prep.sh

set -euo pipefail
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
LOGS_DIR="${CYCLE_LOG_DIR:-$ROOT_DIR/logs}"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

# Derive cycle_id: prefer env var (set by run_cycle.sh), fall back to timestamp
CYCLE_ID="${CYCLE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
AUDIT_DIR="$ROOT_DIR/audit-reports/$CYCLE_ID"

mkdir -p "$AUDIT_DIR" "$STATE_DIR" "$LOGS_DIR"

timestamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

echo "[$(timestamp)] audit_cycle_prep starting (cycle_id=$CYCLE_ID)" >&2

# ---------------------------------------------------------------------------
# Step 1: Existing benchmark + run prep (scan-optimizer logic)
# ---------------------------------------------------------------------------
# This writes state/latest-context.md, state/hermes-prompt.txt, etc.
# Inherited from run_cycle_prep.sh — we keep all its side-effects.
echo "[$(timestamp)] running run_cycle_prep.sh..." >&2
set +e
bash "$ROOT_DIR/scripts/run_cycle_prep.sh" 2>&1
prep_exit=$?
set -e

if [[ $prep_exit -ne 0 ]]; then
    echo "[$(timestamp)] warning: run_cycle_prep.sh exited with $prep_exit; continuing with orchestrator audit" >&2
fi

# ---------------------------------------------------------------------------
# Step 2: Orchestrator health check
# ---------------------------------------------------------------------------
orch_health="down"
if curl -fsSL "$ORCH_BASE_URL/healthz" >/dev/null 2>&1 || \
   orchestrator_curl "$ORCH_BASE_URL/auth/me" >/dev/null 2>&1; then
    orch_health="up"
fi
echo "[$(timestamp)] orchestrator health: $orch_health" >&2

if [[ "$orch_health" == "down" ]]; then
    echo "[$(timestamp)] orchestrator unreachable; writing orchestrator_down marker" >&2
    echo "orchestrator_down" > "$AUDIT_DIR/orch_health"
fi

# ---------------------------------------------------------------------------
# Step 3: Run 3 orchestrator audit scripts in parallel
# ---------------------------------------------------------------------------
echo "[$(timestamp)] launching orchestrator audit scripts in parallel..." >&2

export CYCLE_ID

set +e
(
    export REPORT_PATH="$AUDIT_DIR/api.json"
    bash "$ROOT_DIR/scripts/audit_orchestrator_api.sh" "$CYCLE_ID" \
        > "$AUDIT_DIR/api-audit.log" 2>&1
    echo $? > "$AUDIT_DIR/.api_exit"
) &
api_pid=$!

(
    export REPORT_PATH="$AUDIT_DIR/logs.json"
    bash "$ROOT_DIR/scripts/audit_orchestrator_logs.sh" "$CYCLE_ID" \
        > "$AUDIT_DIR/logs-audit.log" 2>&1
    echo $? > "$AUDIT_DIR/.logs_exit"
) &
logs_pid=$!

(
    python3 "$ROOT_DIR/scripts/audit_orchestrator_features.py" "$CYCLE_ID" \
        > "$AUDIT_DIR/features-audit.log" 2>&1
    echo $? > "$AUDIT_DIR/.features_exit"
) &
features_pid=$!

wait "$api_pid" "$logs_pid" "$features_pid" || true
set -e

api_exit="$(cat "$AUDIT_DIR/.api_exit" 2>/dev/null || echo 1)"
logs_exit="$(cat "$AUDIT_DIR/.logs_exit" 2>/dev/null || echo 1)"
features_exit="$(cat "$AUDIT_DIR/.features_exit" 2>/dev/null || echo 1)"

echo "[$(timestamp)] audit scripts done: api=$api_exit logs=$logs_exit features=$features_exit" >&2

# If any audit script produced no output file, create an empty-findings placeholder
for fname in api.json logs.json features.json; do
    if [[ ! -f "$AUDIT_DIR/$fname" ]]; then
        python3 -c "
import json, sys
from datetime import datetime, timezone
data = {
    'cycle_id': '$CYCLE_ID',
    'source_tag': '${fname%.json}',
    'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'findings': [],
    'pass_count': 0,
    'fail_count': 0,
    'error': 'script did not produce output'
}
print(json.dumps(data, indent=2))
" > "$AUDIT_DIR/$fname"
        echo "[$(timestamp)] warning: $fname was missing; wrote empty placeholder" >&2
    fi
done

# ---------------------------------------------------------------------------
# Step 4: Merge all findings into findings-before.json
# ---------------------------------------------------------------------------
echo "[$(timestamp)] merging findings..." >&2
python3 "$ROOT_DIR/scripts/merge_findings.py" \
    "$AUDIT_DIR/api.json" \
    "$AUDIT_DIR/logs.json" \
    "$AUDIT_DIR/features.json" \
    --out "$AUDIT_DIR/findings-before.json"

total_findings="$(python3 -c "import json; d=json.load(open('$AUDIT_DIR/findings-before.json')); print(d.get('total_findings', 0))" 2>/dev/null || echo 0)"
echo "[$(timestamp)] findings-before.json written: $total_findings total findings" >&2

# ---------------------------------------------------------------------------
# Step 4b: Merge persistent operator-curated findings (if any)
#
# Bugs that survived one or more auditor cycles (because Hermes mis-routed the
# fix, ran out of budget, or made a category-mismatched commit that got
# re-verified elsewhere) can be pinned to this file so every subsequent cycle
# re-discovers them without relying on the automated probes to catch them
# again. Each entry is a standard finding object; id prefix should be
# `PERSIST-` so it's easy to tell them apart from freshly-scanned findings.
# ---------------------------------------------------------------------------
PERSIST_FILE="$STATE_DIR/persistent-findings.json"
if [[ -f "$PERSIST_FILE" ]]; then
    python3 - "$AUDIT_DIR/findings-before.json" "$PERSIST_FILE" "$ROOT_DIR/audit-reports" "$CYCLE_ID" <<'PYEOF'
import json, sys
from pathlib import Path

findings_path = Path(sys.argv[1])
persist_path  = Path(sys.argv[2])
reports_root  = Path(sys.argv[3])
current_cycle = sys.argv[4]
STALENESS_LOOKBACK = 5  # if fingerprint was fixed in any of last N cycles, treat seed as stale

try:
    base = json.loads(findings_path.read_text())
except Exception:
    base = {"findings": [], "deferred": [], "total_findings": 0}
try:
    persist = json.loads(persist_path.read_text())
except Exception:
    sys.exit(0)

persisted = persist.get("findings") or []
if not persisted:
    sys.exit(0)

# Staleness check: for each seed, look at the last N cycles' findings-after.json.
# If the same fingerprint was marked `fixed` AND the fix commit is still in HEAD
# history, the seed is stale — skip injection so we don't manufacture phantom
# findings. Hermes will naturally re-detect the bug via prep's live scans if
# it's actually still broken.
def fingerprint_already_fixed(fp: str) -> tuple[bool, str]:
    if not fp:
        return (False, "")
    cycle_dirs = sorted(
        [p for p in reports_root.iterdir()
         if p.is_dir() and p.name.startswith("2026")
            and not p.name.endswith("-reverify")
            and p.name != current_cycle],
        reverse=True,
    )[:STALENESS_LOOKBACK]
    for cdir in cycle_dirs:
        after_path = cdir / "findings-after.json"
        if not after_path.exists():
            continue
        try:
            doc = json.loads(after_path.read_text())
        except Exception:
            continue
        for f in (doc.get("findings") or []) + (doc.get("deferred") or []):
            if f.get("fingerprint") == fp and f.get("status") == "fixed":
                return (True, f"{cdir.name}/{f.get('commit','?')}")
    return (False, "")

existing_ids = {f.get("id") for f in base.get("findings") or []}
existing_ids.update(f.get("id") for f in base.get("deferred") or [])

new_findings = []
skipped_stale = []
for seed in persisted:
    if seed.get("id") in existing_ids:
        continue
    fp = seed.get("fingerprint")
    is_stale, evidence = fingerprint_already_fixed(fp)
    if is_stale:
        skipped_stale.append((seed.get("id"), fp, evidence))
        continue
    new_findings.append(seed)

if new_findings:
    base.setdefault("findings", []).extend(new_findings)
    base["total_findings"] = len(base["findings"]) + len(base.get("deferred") or [])
    sources = set(base.get("source_tags") or [])
    sources.add("persistent")
    base["source_tags"] = sorted(sources)
    findings_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    print(f"[merge_persistent] added {len(new_findings)} persistent finding(s) from {persist_path.name}")
if skipped_stale:
    for sid, sfp, ev in skipped_stale:
        print(
            f"[merge_persistent] SKIP stale seed {sid} (fingerprint {sfp}): "
            f"already fixed in {ev}. Operator should remove from {persist_path.name}."
        )
PYEOF
fi

# ---------------------------------------------------------------------------
# Step 4c: Persistent-bug rule enforcement.
#
# The skill says: "if a finding has the same fingerprint as one that was
# `fixed` in a previous cycle, the previous fix didn't actually work. Bump
# severity by one level. Evidence should list every prior commit that claimed
# to fix it. Trace the root cause end-to-end, don't just reapply a cosmetic
# tweak to the same file."
#
# Enforcement was purely a judgment call inside Hermes, which reliably
# failed: cycles 210244Z / 224923Z each wrote a new launcher.py:2704 patch
# against an already-fixed bug because they never saw the prior fix history.
# This step makes enforcement deterministic by scanning recent cycles'
# findings-after.json and mutating the current findings-before.json BEFORE
# Hermes reads it: escalate severity, inject prior_fixed_commits list,
# prepend a `PERSISTENT BUG:` line to the reason field.
# ---------------------------------------------------------------------------
if [[ -f "$AUDIT_DIR/findings-before.json" ]]; then
    python3 - "$AUDIT_DIR/findings-before.json" "$ROOT_DIR/audit-reports" "$CYCLE_ID" <<'PYEOF'
import json, sys
from pathlib import Path

findings_path = Path(sys.argv[1])
reports_root  = Path(sys.argv[2])
current_cycle = sys.argv[3]
LOOKBACK = 5  # last 5 cycles is enough to catch recurring patterns without blowing the runtime

try:
    doc = json.loads(findings_path.read_text())
except Exception:
    sys.exit(0)

# Build {fingerprint: [(cycle_id, commit_sha), ...]} over prior cycles.
prior_fixed: dict[str, list[tuple[str, str]]] = {}
cycle_dirs = sorted(
    [p for p in reports_root.iterdir()
     if p.is_dir() and p.name.startswith("2026") and not p.name.endswith("-reverify")
        and p.name != current_cycle],
    reverse=True,
)[:LOOKBACK]
for cdir in cycle_dirs:
    after_path = cdir / "findings-after.json"
    if not after_path.exists():
        continue
    try:
        after = json.loads(after_path.read_text())
    except Exception:
        continue
    for f in (after.get("findings") or []) + (after.get("deferred") or []):
        if f.get("status") != "fixed":
            continue
        fp = f.get("fingerprint")
        if not fp:
            continue
        sha = f.get("commit") or ""
        prior_fixed.setdefault(fp, []).append((cdir.name, sha))

if not prior_fixed:
    sys.exit(0)

SEV_ORDER = ["low", "medium", "high", "critical"]
def bump(sev: str) -> str:
    s = (sev or "").lower()
    if s not in SEV_ORDER:
        return "high"  # unknown → treat as high; persistent bugs are never low
    idx = SEV_ORDER.index(s)
    return SEV_ORDER[min(idx + 1, len(SEV_ORDER) - 1)]

escalated = 0
for f in (doc.get("findings") or []) + (doc.get("deferred") or []):
    fp = f.get("fingerprint")
    if not fp or fp not in prior_fixed:
        continue
    history = prior_fixed[fp]
    # Don't double-escalate a finding that's already been marked persistent.
    if f.get("persistent_bug"):
        continue
    orig_sev = f.get("severity")
    new_sev = bump(orig_sev)
    f["severity"] = new_sev
    f["persistent_bug"] = True
    f["prior_fixed_commits"] = [
        {"cycle_id": cyc, "commit": sha} for cyc, sha in history
    ]
    # Prepend a clear directive to reason so Hermes sees it in Phase 1.
    shas_str = ", ".join(sha[:7] if sha else "?" for _, sha in history)
    banner = (
        f"PERSISTENT BUG: fingerprint {fp} was marked `fixed` in "
        f"{len(history)} prior cycle(s) by commit(s) [{shas_str}]. "
        "The fix did NOT hold — do not re-patch the same file cosmetically; "
        "trace root cause end-to-end (backend state flow, supervisor races, "
        "stale bytecode, missing restart, seed staleness). If investigation "
        "shows the code IS actually fixed and the finding is being re-injected "
        "by a stale seed or cached artifact, mark it `reclassified` with the "
        "specific stale-source reason. DO NOT make another same-site patch."
    )
    existing_reason = (f.get("reason") or "").strip()
    f["reason"] = banner + (f"\n\nPrior reason: {existing_reason}" if existing_reason else "")
    escalated += 1

if escalated:
    findings_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"[persistent-bug-rule] escalated {escalated} finding(s) based on prior-cycle fix history")
PYEOF
fi

# Step 4d removed 2026-04-25: recall regression report is generated by
# run_cycle.sh AFTER the local benchmark run completes and its score is
# persisted to benchmark-metrics-history.json. Running it here, before
# the local run has finished, only re-reads stale data — operator
# feedback: "跑一半就分析没有任何意义".

# ---------------------------------------------------------------------------
# Step 5: Append auditor context to latest-context.md
# ---------------------------------------------------------------------------
CONTEXT_FILE="$STATE_DIR/latest-context.md"
baseline_sha="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"

{
    echo ""
    echo "## Auditor Cycle Context"
    echo "- cycle_id: $CYCLE_ID"
    echo "- baseline_sha: $baseline_sha"
    echo "- orchestrator_health: $orch_health"
    echo "- audit_dir: $AUDIT_DIR"
    echo ""
    echo "### Findings Summary"
    echo "- total_findings: $total_findings"
    if [[ -f "$AUDIT_DIR/findings-before.json" ]]; then
        python3 - <<PYEOF
import json
from pathlib import Path

data = json.loads(Path("$AUDIT_DIR/findings-before.json").read_text())
findings = data.get("findings") or []
deferred = data.get("deferred") or []
by_cat: dict[str, int] = {}
by_sev: dict[str, int] = {}
for f in findings + deferred:
    cat = f.get("category", "unknown")
    sev = f.get("severity", "low")
    by_cat[cat] = by_cat.get(cat, 0) + 1
    by_sev[sev] = by_sev.get(sev, 0) + 1
for sev in ("critical", "high", "medium", "low"):
    if sev in by_sev:
        print(f"- {sev}: {by_sev[sev]}")
print()
print("#### By category:")
for cat, count in sorted(by_cat.items()):
    print(f"- {cat}: {count}")
PYEOF
    fi
    echo ""
    echo "### Scheduled for Phase 2 (top N):"
    if [[ -f "$AUDIT_DIR/findings-before.json" ]]; then
        python3 - <<PYEOF
import json
from pathlib import Path

data = json.loads(Path("$AUDIT_DIR/findings-before.json").read_text())
for f in (data.get("findings") or []):
    print(f"- [{f.get('severity','?').upper()}] {f.get('id','?')}: {f.get('summary','?')}")
PYEOF
    fi
} >> "$CONTEXT_FILE"

# ---------------------------------------------------------------------------
# Step 6: Overwrite hermes-prompt.txt with the auditor-specific prompt.
# run_cycle_prep.sh (called in Step 1) already wrote the scan-optimizer
# prompt into state/hermes-prompt.txt — leaving that in place would make
# Hermes run scan-optimizer work inside the auditor cycle.
# ---------------------------------------------------------------------------
PROMPT_SRC="$ROOT_DIR/prompts/redteam-auditor-loop.txt"
PROMPT_DST="$STATE_DIR/hermes-prompt.txt"
if [[ ! -f "$PROMPT_SRC" ]]; then
    echo "[$(timestamp)] fatal: missing auditor prompt template at $PROMPT_SRC" >&2
    exit 2
fi

# Substitute ${CYCLE_ID} into the template.
export CYCLE_ID
python3 - "$PROMPT_SRC" "$PROMPT_DST" <<'PYEOF'
import os, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
cycle_id = os.environ.get("CYCLE_ID", "")
text = text.replace("${CYCLE_ID}", cycle_id)
with open(dst, "w") as fh:
    fh.write(text)
PYEOF

echo "[$(timestamp)] auditor prompt written to $PROMPT_DST" >&2

echo "[$(timestamp)] audit_cycle_prep complete" >&2
echo "[$(timestamp)] - context: $CONTEXT_FILE" >&2
echo "[$(timestamp)] - findings: $AUDIT_DIR/findings-before.json" >&2
echo "[$(timestamp)] - prompt:   $PROMPT_DST" >&2
