#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
PROMPTS_DIR="$ROOT_DIR/prompts"
LOGS_DIR="${CYCLE_LOG_DIR:-$ROOT_DIR/logs}"
REFRESH_ORCHESTRATOR="${REFRESH_ORCHESTRATOR:-1}"

mkdir -p "$STATE_DIR" "$LOGS_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
ORCH_TOKEN="${ORCH_TOKEN:-}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
TARGET_OKX="${TARGET_OKX:-https://www.okx.com}"
TARGET_LOCAL="${TARGET_LOCAL:-http://127.0.0.1:8000}"

LATEST_RUNS_JSON="$STATE_DIR/latest-runs.json"


timestamp() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

refresh_runs_json() {
    orchestrator_curl \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$LATEST_RUNS_JSON"
}

latest_run_id_for_target() {
    local target="$1"
    jq -r --arg target "$target" '
        [ .[] | select(.target == $target) ] | last.id // empty
    ' "$LATEST_RUNS_JSON"
}

verify_live_projection() {
    local run_id="$1"
    local label="$2"
    [[ -n "$run_id" ]] || return 0

    local snapshot_json
    snapshot_json="$(python3 "$ROOT_DIR/scripts/run_context_snapshot.py" "$run_id")"

    local projection_mismatch artifact_reasons
    projection_mismatch="$(printf '%s\n' "$snapshot_json" | jq -r '((.artifact.integrity.summary_api_suspicious // false) or (.artifact.integrity.observed_api_suspicious // false))')"
    artifact_reasons="$(printf '%s\n' "$snapshot_json" | jq -r '(.artifact.integrity.reasons // []) | map(select(startswith("artifact_"))) | join(", ")')"

    if [[ "$projection_mismatch" == "true" ]]; then
        echo "[$(timestamp)] live projection mismatch for $label run $run_id" >&2
        printf '%s\n' "$snapshot_json" | jq '{run_id: .summary.target.target, integrity: .artifact.integrity, api_coverage: .summary.coverage, artifact_cases: .artifact.cases}' >&2
        return 1
    fi

    if [[ -n "$artifact_reasons" ]]; then
        echo "[$(timestamp)] non-fatal artifact anomaly for $label run $run_id: $artifact_reasons" >&2
    fi

    return 0
}

verify_fixed_target_runs() {
    local needs_rebuild=0
    refresh_runs_json

    local okx_id local_id
    okx_id="$(latest_run_id_for_target "$TARGET_OKX")"
    local_id="$(latest_run_id_for_target "$TARGET_LOCAL")"

    verify_live_projection "$okx_id" "okx" || needs_rebuild=1
    verify_live_projection "$local_id" "local" || needs_rebuild=1

    return "$needs_rebuild"
}

if [[ "$REFRESH_ORCHESTRATOR" == "1" ]]; then
    echo "[$(timestamp)] restarting local orchestrator to refresh live run state before snapshot..."
    (
        cd "$REPO_DIR"
        ./orchestrator/stop.sh >/dev/null 2>&1 || true
        ./orchestrator/run.sh
    ) | tee "$LOGS_DIR/orchestrator-refresh.log"

    if ! verify_fixed_target_runs; then
        echo "[$(timestamp)] plain restart left summary/observed-path drift; rebuilding orchestrator..." | tee -a "$LOGS_DIR/orchestrator-refresh.log"
        (
            cd "$REPO_DIR"
            ./orchestrator/stop.sh >/dev/null 2>&1 || true
            ./orchestrator/run.sh --rebuild
        ) | tee -a "$LOGS_DIR/orchestrator-refresh.log"

        verify_fixed_target_runs
    fi
fi

echo "[$(timestamp)] building latest run context before taking action..."
"$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"

cp "$PROMPTS_DIR/scan-optimizer-loop.txt" "$STATE_DIR/openclaw-prompt.txt"

echo "[$(timestamp)] prepared OpenClaw cycle inputs:"
echo "- context: $STATE_DIR/latest-context.md"
echo "- prompt:  $STATE_DIR/openclaw-prompt.txt"
