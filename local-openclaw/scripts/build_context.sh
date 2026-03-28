#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
ORCH_TOKEN="${ORCH_TOKEN:?set ORCH_TOKEN}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"

mkdir -p "$STATE_DIR"

latest_runs_json="$STATE_DIR/latest-runs.json"
latest_context_md="$STATE_DIR/latest-context.md"

curl -fsS \
    -H "Authorization: Bearer $ORCH_TOKEN" \
    "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$latest_runs_json"

run_context_snapshot() {
    local run_id="$1"
    python3 "$ROOT_DIR/scripts/run_context_snapshot.py" "$run_id"
}

orchestrator_events() {
    local run_id="$1"
    curl -fsS \
        -H "Authorization: Bearer $ORCH_TOKEN" \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs/$run_id/events"
}

crawler_health_report() {
    local run_id="$1"
    local label="$2"
    "$ROOT_DIR/scripts/crawler_health_report.sh" "$run_id" "$label"
}

okx_id="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.id // empty' "$latest_runs_json")"
local_id="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.id // empty' "$latest_runs_json")"

{
    echo "# Latest Scan Optimizer Context"
    echo
    echo "## Runs"
    echo
    jq '.' "$latest_runs_json"
    echo
    if [[ -n "$okx_id" ]]; then
        okx_snapshot="$(run_context_snapshot "$okx_id")"
        echo "## OKX Summary"
        echo
        printf '%s\n' "$okx_snapshot" | jq '.summary'
        echo
        echo "## OKX Observed Paths"
        echo
        printf '%s\n' "$okx_snapshot" | jq '.observed_paths'
        echo
        echo "## OKX Artifact Snapshot"
        echo
        printf '%s\n' "$okx_snapshot" | jq '.artifact'
        echo
        echo "## OKX Events"
        echo
        orchestrator_events "$okx_id" | jq '.'
        echo
        crawler_health_report "$okx_id" "OKX"
        echo
    fi
    if [[ -n "$local_id" ]]; then
        local_snapshot="$(run_context_snapshot "$local_id")"
        echo "## Local Summary"
        echo
        printf '%s\n' "$local_snapshot" | jq '.summary'
        echo
        echo "## Local Observed Paths"
        echo
        printf '%s\n' "$local_snapshot" | jq '.observed_paths'
        echo
        echo "## Local Artifact Snapshot"
        echo
        printf '%s\n' "$local_snapshot" | jq '.artifact'
        echo
        echo "## Local Events"
        echo
        orchestrator_events "$local_id" | jq '.'
        echo
        crawler_health_report "$local_id" "Local"
        echo
    fi
} > "$latest_context_md"

printf '%s\n' "$latest_context_md"
