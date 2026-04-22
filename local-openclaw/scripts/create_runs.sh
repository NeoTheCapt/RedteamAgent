#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
ORCH_TOKEN="${ORCH_TOKEN:-}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"

TARGET_OKX="${TARGET_OKX:-https://www.okx.com}"
TARGET_LOCAL="${TARGET_LOCAL:-http://127.0.0.1:8000}"
FORCE_REPLACE_ACTIVE_RUNS="${FORCE_REPLACE_ACTIVE_RUNS:-0}"
# Optional comma-separated subset of fixed targets to manage for this invocation.
# Accepted values: okx, local, the full target URL, or all.
TARGET_FILTER_RAW="${TARGET_FILTER:-all}"
TARGET_FILTER="${TARGET_FILTER_RAW//[[:space:]]/}"

api_get_runs() {
    orchestrator_curl \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs"
}

create_run() {
    local target="$1"
    orchestrator_curl \
        -H "Content-Type: application/json" \
        -X POST \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" \
        -d "$(jq -nc --arg t "$target" '{target: $t}')"
}

delete_run() {
    local run_id="$1"
    orchestrator_curl \
        -X DELETE \
        "$ORCH_BASE_URL/projects/$PROJECT_ID/runs/$run_id" >/dev/null
}

# Trailing-slash tolerant jq filter shared across functions.
_JQ_TARGET_MATCH='def tm($t): (.target == $t or .target == ($t + "/") or .target == ($t | rtrimstr("/")));'

latest_active_run_json() {
    local runs_json="$1"
    local target="$2"
    printf '%s' "$runs_json" | jq -c --arg target "$target" "$_JQ_TARGET_MATCH"'
        [ .[] | select(tm($target) and (.status == "queued" or .status == "running")) ]
        | last // empty
    '
}

cleanup_target_runs() {
    local runs_json="$1"
    local target="$2"
    local keep_id="${3:-}"

    while IFS=$'\t' read -r run_id run_status; do
        [[ -z "${run_id:-}" ]] && continue
        if [[ -n "$keep_id" && "$run_id" == "$keep_id" ]]; then
            continue
        fi
        echo "deleting stale/extra run ${run_id} for ${target} (status=${run_status})" >&2
        if ! delete_run "$run_id"; then
            echo "warning: failed to delete run ${run_id} for ${target}" >&2
        fi
    done < <(
        printf '%s' "$runs_json" | jq -r --arg target "$target" "$_JQ_TARGET_MATCH"'
            .[]
            | select(tm($target))
            | "\(.id)\t\(.status)"
        '
    )
}

ensure_single_active_run() {
    local runs_json="$1"
    local target="$2"

    if [[ -z "$target" ]]; then
        echo "null"
        return 0
    fi

    if [[ "$FORCE_REPLACE_ACTIVE_RUNS" == "1" ]]; then
        local active_count
        active_count="$(printf '%s' "$runs_json" | jq --arg target "$target" "$_JQ_TARGET_MATCH"'
            [ .[] | select(tm($target) and (.status == "queued" or .status == "running")) ] | length')"
        if (( active_count > 0 )); then
            echo "force-replacing ${active_count} active run(s) for ${target}" >&2
        fi
        cleanup_target_runs "$runs_json" "$target"
        create_run "$target"
        return 0
    fi

    local active_json
    active_json="$(latest_active_run_json "$runs_json" "$target")"

    if [[ -n "$active_json" && "$active_json" != "null" ]]; then
        local keep_id
        keep_id="$(printf '%s' "$active_json" | jq -r '.id')"
        cleanup_target_runs "$runs_json" "$target" "$keep_id"
        echo "reusing active run ${keep_id} for ${target}" >&2
        printf '%s' "$active_json"
        return 0
    fi

    cleanup_target_runs "$runs_json" "$target"
    echo "creating fresh run for ${target}" >&2
    create_run "$target"
}

should_manage_target() {
    local label="$1"
    local target="$2"
    local entry

    if [[ -z "$TARGET_FILTER" || "$TARGET_FILTER" == "all" ]]; then
        return 0
    fi

    IFS=',' read -r -a filters <<< "$TARGET_FILTER"
    for entry in "${filters[@]}"; do
        [[ -z "$entry" ]] && continue
        if [[ "$entry" == "$label" || "$entry" == "$target" || "$entry" == "all" ]]; then
            return 0
        fi
    done

    return 1
}

current_active_or_null() {
    local runs_json="$1"
    local target="$2"
    local active_json
    active_json="$(latest_active_run_json "$runs_json" "$target")"
    if [[ -n "$active_json" && "$active_json" != "null" ]]; then
        printf '%s' "$active_json"
    else
        printf 'null'
    fi
}

if [[ "$TARGET_FILTER" != "all" ]]; then
    matched=0
    should_manage_target okx "$TARGET_OKX" && matched=1
    should_manage_target local "$TARGET_LOCAL" && matched=1
    if [[ "$matched" -ne 1 ]]; then
        echo "TARGET_FILTER did not match any fixed target: ${TARGET_FILTER_RAW}" >&2
        exit 1
    fi
fi

runs_json="$(api_get_runs)"
if should_manage_target okx "$TARGET_OKX"; then
    ensure_single_active_run "$runs_json" "$TARGET_OKX" >/dev/null
fi
if should_manage_target local "$TARGET_LOCAL"; then
    # Re-fetch after OKX management: the prior step may have created or deleted runs,
    # so the local target needs a fresh view of orchestrator state.
    runs_json="$(api_get_runs)"
    ensure_single_active_run "$runs_json" "$TARGET_LOCAL" >/dev/null
fi

final_runs_json="$(api_get_runs)"
okx_payload="$(current_active_or_null "$final_runs_json" "$TARGET_OKX")"
local_payload="$(current_active_or_null "$final_runs_json" "$TARGET_LOCAL")"

mkdir -p "$STATE_DIR"
cat > "$STATE_DIR/latest-created-runs.json" <<EOF
{
  "okx": $okx_payload,
  "local": $local_payload
}
EOF

printf '%s\n' "$okx_payload"
printf '%s\n' "$local_payload"
