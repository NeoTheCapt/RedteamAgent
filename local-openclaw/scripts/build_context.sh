#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

export ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
export ORCH_TOKEN="${ORCH_TOKEN:-}"
export PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"

mkdir -p "$STATE_DIR"

latest_runs_json="$STATE_DIR/latest-runs.json"
latest_context_md="$STATE_DIR/latest-context.md"

orchestrator_curl \
    "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" > "$latest_runs_json"

run_context_snapshot() {
    local run_id="$1"
    python3 "$ROOT_DIR/scripts/run_context_snapshot.py" "$run_id"
}

orchestrator_events() {
    local run_id="$1"
    orchestrator_curl \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs/$run_id/events"
}

crawler_health_report() {
    local run_id="$1"
    local label="$2"
    "$ROOT_DIR/scripts/crawler_health_report.sh" "$run_id" "$label"
}

benchmark_findings_report() {
    local snapshot_json="$1"
    local label="$2"
    local mapping_file="$STATE_DIR/target-benchmarks.json"
    [[ -f "$mapping_file" ]] || return 0
    printf '%s\n' "$snapshot_json" | python3 "$ROOT_DIR/scripts/findings_benchmark_eval.py" \
        --mapping "$mapping_file" \
        --root-dir "$ROOT_DIR" \
        --openclaw-bin "${OPENCLAW_BIN:-openclaw}" \
        --label "$label"
}

okx_id="$(jq -r '[ .[] | select(.target=="https://www.okx.com") ] | last.id // empty' "$latest_runs_json")"
local_id="$(jq -r '[ .[] | select(.target=="http://127.0.0.1:8000") ] | last.id // empty' "$latest_runs_json")"
fixed_target_state_json="$(jq \
    --arg okx "https://www.okx.com" \
    --arg local "http://127.0.0.1:8000" '
        def active_runs($target): [ .[] | select(.target == $target and (.status == "queued" or .status == "running")) ];
        def latest_run($target): ([ .[] | select(.target == $target) ] | last // null);
        {
          okx: {
            target: $okx,
            total_runs: ([ .[] | select(.target == $okx) ] | length),
            active_runs: (active_runs($okx) | length),
            latest_run: latest_run($okx)
          },
          local: {
            target: $local,
            total_runs: ([ .[] | select(.target == $local) ] | length),
            active_runs: (active_runs($local) | length),
            latest_run: latest_run($local)
          },
          unexpected_active_runs: [
            .[]
            | select((.status == "queued" or .status == "running") and (.target != $okx and .target != $local))
            | {
                id,
                target,
                status,
                created_at,
                updated_at,
                ended_at,
                stop_reason_code,
                stop_reason_text
              }
          ]
        }
    ' "$latest_runs_json")"

{
    echo "# Latest Scan Optimizer Context"
    echo
    echo "## Fixed Target State"
    echo
    printf '%s\n' "$fixed_target_state_json" | jq '.'
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
        echo "## OKX Benchmark Evaluation"
        echo
        benchmark_findings_report "$okx_snapshot" "OKX Benchmark Evaluation"
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
        echo "## Local Benchmark Evaluation"
        echo
        benchmark_findings_report "$local_snapshot" "Local Benchmark Evaluation"
        echo
    fi
} > "$latest_context_md"

printf '%s\n' "$latest_context_md"
