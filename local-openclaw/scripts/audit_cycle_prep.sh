#!/usr/bin/env bash
# audit_cycle_prep.sh — unified cycle prep for redteam-auditor-hermes
#
# Chains existing scan-optimizer prep (run_cycle_prep.sh) with the 3 new
# orchestrator audit scripts, then merges all findings-before.json and
# appends a unified context to latest-context.md.
#
# Usage: Called automatically by run_cycle.sh when OPENCLAW_SKILL=redteam-auditor-hermes
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
# This writes state/latest-context.md, state/openclaw-prompt.txt, etc.
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
    python3 - "$AUDIT_DIR/findings-before.json" "$PERSIST_FILE" <<'PYEOF'
import json, sys
from pathlib import Path

findings_path = Path(sys.argv[1])
persist_path  = Path(sys.argv[2])
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

existing_ids = {f.get("id") for f in base.get("findings") or []}
existing_ids.update(f.get("id") for f in base.get("deferred") or [])
new_findings = [f for f in persisted if f.get("id") not in existing_ids]

if new_findings:
    base.setdefault("findings", []).extend(new_findings)
    base["total_findings"] = len(base["findings"]) + len(base.get("deferred") or [])
    sources = set(base.get("source_tags") or [])
    sources.add("persistent")
    base["source_tags"] = sorted(sources)
    findings_path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    print(f"[merge_persistent] added {len(new_findings)} persistent finding(s) from {persist_path.name}")
PYEOF
fi

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
# Step 6: Overwrite openclaw-prompt.txt with the auditor-specific prompt.
# run_cycle_prep.sh (called in Step 1) already wrote the scan-optimizer
# prompt into state/openclaw-prompt.txt — leaving that in place would make
# Hermes run scan-optimizer work inside the auditor cycle.
# ---------------------------------------------------------------------------
PROMPT_SRC="$ROOT_DIR/prompts/redteam-auditor-loop.txt"
PROMPT_DST="$STATE_DIR/openclaw-prompt.txt"
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
