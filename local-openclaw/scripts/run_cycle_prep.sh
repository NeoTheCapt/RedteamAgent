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

# Target URL matching tolerates trailing-slash differences:
# orchestrator may store "http://host:8000/" while config uses "http://host:8000".
_target_matches() {
    # Usage: jq select filter that matches with or without trailing slash.
    local target="$1"
    local stripped="${target%/}"
    printf '(.target == "%s" or .target == "%s/")' "$stripped" "$stripped"
}

latest_run_id_for_target() {
    local target="$1"
    local filter
    filter="$(_target_matches "$target")"
    jq -r "[ .[] | select($filter) ] | last.id // empty" "$LATEST_RUNS_JSON"
}

active_run_count_for_target() {
    local target="$1"
    local filter
    filter="$(_target_matches "$target")"
    jq -r "[ .[] | select($filter and (.status == \"queued\" or .status == \"running\")) ] | length" "$LATEST_RUNS_JSON"
}

unexpected_active_runs_json() {
    local okx_filter local_filter
    okx_filter="$(_target_matches "$TARGET_OKX")"
    local_filter="$(_target_matches "$TARGET_LOCAL")"
    jq -c "[ .[] | select((.status == \"queued\" or .status == \"running\") and ($okx_filter | not) and ($local_filter | not)) ]" "$LATEST_RUNS_JSON"
}

verify_live_projection() {
    local run_id="$1"
    local label="$2"
    [[ -n "$run_id" ]] || return 0

    local snapshot_helper="$ROOT_DIR/scripts/run_context_snapshot.py"
    if [[ ! -f "$snapshot_helper" ]]; then
        echo "[$(timestamp)] warning: missing $snapshot_helper; skipping live projection verification for $label run $run_id" >&2
        return 0
    fi

    local snapshot_json
    snapshot_json="$(python3 "$snapshot_helper" "$run_id")"

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

    local okx_filter local_filter okx_id local_id okx_active_count local_active_count unexpected_active_json unexpected_active_count okx_status local_status expected_local_active_count
    okx_filter="$(_target_matches "$TARGET_OKX")"
    local_filter="$(_target_matches "$TARGET_LOCAL")"
    okx_id="$(latest_run_id_for_target "$TARGET_OKX")"
    local_id="$(latest_run_id_for_target "$TARGET_LOCAL")"
    okx_active_count="$(active_run_count_for_target "$TARGET_OKX")"
    local_active_count="$(active_run_count_for_target "$TARGET_LOCAL")"
    okx_status="$(jq -r "[ .[] | select($okx_filter) ] | last.status // empty" "$LATEST_RUNS_JSON")"
    local_status="$(jq -r "[ .[] | select($local_filter) ] | last.status // empty" "$LATEST_RUNS_JSON")"
    unexpected_active_json="$(unexpected_active_runs_json)"
    unexpected_active_count="$(printf '%s\n' "$unexpected_active_json" | jq 'length')"

    if [[ -z "$okx_id" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: no latest run exists for $TARGET_OKX" >&2
        needs_rebuild=1
    fi
    if [[ -z "$local_id" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: no latest run exists for $TARGET_LOCAL" >&2
        needs_rebuild=1
    fi
    if [[ "$okx_active_count" != "1" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: expected exactly 1 active run for $TARGET_OKX but found $okx_active_count" >&2
        needs_rebuild=1
    fi

    expected_local_active_count=1
    case "$local_status" in
        completed|complete|succeeded|success)
            expected_local_active_count=0
            ;;
    esac

    if [[ "$local_active_count" != "$expected_local_active_count" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: expected $expected_local_active_count active run(s) for $TARGET_LOCAL with latest status '$local_status' but found $local_active_count" >&2
        needs_rebuild=1
    fi
    if [[ "$unexpected_active_count" != "0" ]]; then
        echo "[$(timestamp)] fixed-target anomaly: unexpected active non-fixed-target runs detected:" >&2
        printf '%s\n' "$unexpected_active_json" | jq '.' >&2
        needs_rebuild=1
    fi

    # Only verify projection for active runs. Failed/completed runs may have
    # corrupted artifacts that cause permanent projection mismatch.
    if (( okx_active_count > 0 )); then
        verify_live_projection "$okx_id" "okx" || needs_rebuild=1
    fi
    if (( local_active_count > 0 )); then
        verify_live_projection "$local_id" "local" || needs_rebuild=1
    fi

    return "$needs_rebuild"
}

# Distinguish run-state drift (no active run, wrong active count) from
# projection drift (summary/observed-path mismatch with DB). Only the
# latter is fixable by restarting/rebuilding uvicorn — the former is fixed
# by recover_abnormal_runs below (API call, no image rebuild needed).
# Before this split, both classes triggered `run.sh --rebuild`, and every
# time a target had no active run it rebuilt redteam-allinone (7.5 GB) for
# nothing. Over ~2 weeks that garbage filled 160 GB of disk and took
# OrbStack with it.
has_projection_drift() {
    refresh_runs_json || return 0  # no data → no drift claim
    local okx_id local_id
    okx_id="$(latest_run_id_for_target "$TARGET_OKX")"
    local_id="$(latest_run_id_for_target "$TARGET_LOCAL")"
    local okx_active local_active
    okx_active="$(active_run_count_for_target "$TARGET_OKX")"
    local_active="$(active_run_count_for_target "$TARGET_LOCAL")"
    if (( okx_active > 0 )); then
        verify_live_projection "$okx_id" "okx" || return 1
    fi
    if (( local_active > 0 )); then
        verify_live_projection "$local_id" "local" || return 1
    fi
    return 0
}

if [[ "$REFRESH_ORCHESTRATOR" == "1" ]]; then
    # Only restart when orchestrator is unreachable OR a LIVE projection
    # is genuinely drifted. Run-state anomalies (no run, wrong count) are
    # deferred to recover_abnormal_runs so we don't pay for a rebuild when
    # the real fix is a POST /runs API call.
    if ! orchestrator_curl "$ORCH_BASE_URL/projects/$PROJECT_ID/runs" >/dev/null 2>&1; then
        echo "[$(timestamp)] orchestrator unreachable; restarting..."
        needs_restart=1
    elif ! has_projection_drift; then
        echo "[$(timestamp)] orchestrator healthy and projections clean; skipping restart"
        needs_restart=0
    else
        echo "[$(timestamp)] projection drift detected; restarting..."
        needs_restart=1
    fi

    if [[ "${needs_restart:-0}" == "1" ]]; then
        (
            cd "$REPO_DIR"
            ./orchestrator/stop.sh >/dev/null 2>&1 || true
            ./orchestrator/run.sh
        ) | tee "$LOGS_DIR/orchestrator-refresh.log"

        # Rebuild is now LAST RESORT — only when a plain restart can't bring
        # the orchestrator back up AND projection is still drifted. Rebuilding
        # agent/docker/redteam-allinone cannot fix uvicorn's in-memory state,
        # and it never fixes "no run exists"; those were the two 90% cases
        # that used to push us into the rebuild branch.
        if ! orchestrator_curl "$ORCH_BASE_URL/healthz" >/dev/null 2>&1; then
            echo "[$(timestamp)] orchestrator still unreachable after restart; rebuilding image as last resort..." | tee -a "$LOGS_DIR/orchestrator-refresh.log"
            (
                cd "$REPO_DIR"
                ./orchestrator/stop.sh >/dev/null 2>&1 || true
                ./orchestrator/run.sh --rebuild
            ) | tee -a "$LOGS_DIR/orchestrator-refresh.log"
            if ! orchestrator_curl "$ORCH_BASE_URL/healthz" >/dev/null 2>&1; then
                echo "[$(timestamp)] orchestrator unreachable even after rebuild; continuing into recover_abnormal_runs but prep is degraded" >&2
            fi
        elif has_projection_drift; then
            echo "[$(timestamp)] projection still drifted after restart; leaving to recover_abnormal_runs (rebuild would not fix live projection drift)" >&2
        fi
    fi
fi

append_benchmark_context() {
    local prompt_file="$1"
    local history_file="$STATE_DIR/benchmark-metrics-history.json"

    # Include challenge recall history so OpenClaw knows the recent trajectory.
    python3 - "$history_file" >> "$prompt_file" <<'PY'
import json, sys
from pathlib import Path

history_path = Path(sys.argv[1])
target = "http://127.0.0.1:8000"

history = {}
if history_path.exists():
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        pass
target_state = ((history.get("targets") or {}).get(target) or {})
records = list(target_state.get("history") or [])

print("\n## Challenge Score History\n")
if records:
    for record in records[-5:]:
        metrics = (record or {}).get("metrics") or {}
        cycle_id = (record or {}).get("cycle_id", "?")
        cr = metrics.get("challenge_recall", "?")
        solved = metrics.get("solved_challenges", "?")
        total = metrics.get("total_challenges", "?")
        print(f"- cycle {cycle_id}: recall={cr}, solved={solved}/{total}")
else:
    print("- No challenge score history available yet.")
PY
}

# Per-target run status helper.
latest_run_status_for_target() {
    local target="$1"
    local filter
    filter="$(_target_matches "$target")"
    jq -r "[ .[] | select($filter) ] | last.status // empty" "$LATEST_RUNS_JSON"
}

# Proactive recovery for non-active runs.
# OKX: long-lived target — only queued/running is normal. Any terminal state
#       (completed/failed/error/stopped) triggers deletion and recreation.
# Local (Juice Shop): completed is expected (ready for scoring). Only
#       failed/error/stopped triggers recreation with Juice Shop restart.
recover_abnormal_runs() {
    refresh_runs_json
    local okx_status local_status needs_recovery=0
    okx_status="$(latest_run_status_for_target "$TARGET_OKX")"
    local_status="$(latest_run_status_for_target "$TARGET_LOCAL")"

    case "$okx_status" in
        failed|failure|error|errored|stopped|cancelled|canceled|timeout)
            # Preserve the terminal run so the auditor's agent_bug source can
            # still read log.md / run.json / findings when analyzing what went
            # wrong. Without KEEP_TERMINAL_RUNS the DELETE endpoint would
            # rmtree the engagement directory before Hermes gets to see it.
            echo "[$(timestamp)] OKX run is abnormal (status=$okx_status); creating fresh replacement (preserving failed run for post-mortem)" >&2
            if TARGET_FILTER=okx FORCE_REPLACE_ACTIVE_RUNS=1 KEEP_TERMINAL_RUNS=1 "$ROOT_DIR/scripts/create_runs.sh" >&2; then
                needs_recovery=1
            else
                echo "[$(timestamp)] warning: failed to create OKX replacement run" >&2
            fi
            ;;
        "")
            echo "[$(timestamp)] no OKX run exists; creating one" >&2
            if TARGET_FILTER=okx "$ROOT_DIR/scripts/create_runs.sh" >&2; then
                needs_recovery=1
            else
                echo "[$(timestamp)] warning: failed to create OKX run" >&2
            fi
            ;;
        completed|complete|succeeded|success)
            echo "[$(timestamp)] OKX run terminated (status=$okx_status); OKX is a long-lived target — deleting and recreating" >&2
            if TARGET_FILTER=okx FORCE_REPLACE_ACTIVE_RUNS=1 "$ROOT_DIR/scripts/create_runs.sh" >&2; then
                needs_recovery=1
            else
                echo "[$(timestamp)] warning: failed to recreate OKX run" >&2
            fi
            ;;
        *)
            echo "[$(timestamp)] OKX run active (status=$okx_status); leaving as-is" >&2
            ;;
    esac

    case "$local_status" in
        failed|failure|error|errored|stopped|cancelled|canceled|timeout)
            echo "[$(timestamp)] local run is abnormal (status=$local_status); creating replacement (preserving failed run for post-mortem; Juice Shop NOT restarted — deferred to post-cycle)" >&2
            if TARGET_FILTER=local FORCE_REPLACE_ACTIVE_RUNS=1 KEEP_TERMINAL_RUNS=1 "$ROOT_DIR/scripts/create_runs.sh" >&2; then
                needs_recovery=1
            else
                echo "[$(timestamp)] warning: failed to create local replacement run" >&2
            fi
            ;;
        "")
            echo "[$(timestamp)] no local run exists; creating one (Juice Shop NOT restarted — deferred to post-cycle)" >&2
            if TARGET_FILTER=local "$ROOT_DIR/scripts/create_runs.sh" >&2; then
                needs_recovery=1
            else
                echo "[$(timestamp)] warning: failed to create local run" >&2
            fi
            ;;
        completed|complete|succeeded|success)
            echo "[$(timestamp)] local run completed (status=$local_status); ready for scoring" >&2
            ;;
        *)
            echo "[$(timestamp)] local run active (status=$local_status); waiting for completion" >&2
            ;;
    esac

    return $needs_recovery
}

recover_abnormal_runs || true

# Check if local run is completed — if so, skip the observation window (the run
# is done, challenge score is ready now) and build context immediately.
# After building context with the completed run's score, restart Juice Shop and
# create a fresh run so the NEXT cycle has a running target to observe.
refresh_runs_json
_local_status_now="$(latest_run_status_for_target "$TARGET_LOCAL")"
case "$_local_status_now" in
    completed|complete|succeeded|success)
        # Check if this specific completed run was already scored in a prior cycle.
        completed_run_id="$(latest_run_id_for_target "$TARGET_LOCAL")"
        last_scored_run_id=""
        if [[ -f "$STATE_DIR/last-scored-run-id" ]]; then
            last_scored_run_id="$(cat "$STATE_DIR/last-scored-run-id" 2>/dev/null || true)"
        fi

        if [[ -n "$completed_run_id" && "$completed_run_id" == "$last_scored_run_id" ]]; then
            echo "[$(timestamp)] local run $completed_run_id already scored in a prior cycle; Phase 2 will be skipped"
            OPENCLAW_SKIP_JUICE_SHOP_SCORE=1 "$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"
            # Refresh the local run. Without this, cycles keep observing the same
            # completed run forever — the post-cycle restart path is gated on
            # (scored_this_cycle AND new_commit), neither of which fires when
            # the run was already scored in a prior cycle. OKX path already
            # refreshes on `completed` via recover_abnormal_runs; this mirrors
            # that semantics for the local target once scoring is stale.
            echo "[$(timestamp)] local run $completed_run_id stale (already scored); restarting Juice Shop + creating fresh run" >&2
            if command -v docker >/dev/null 2>&1; then
                docker restart juice-shop >/dev/null 2>&1 || echo "[$(timestamp)] warning: docker restart juice-shop failed" >&2
                sleep 3
            fi
            set +e
            FORCE_REPLACE_ACTIVE_RUNS=1 TARGET_FILTER=local "$ROOT_DIR/scripts/create_runs.sh" >&2
            set -e
            refresh_runs_json
        else
            echo "[$(timestamp)] local run $completed_run_id completed (new); scoring challenge recall..."
            "$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"
            if grep -q "^- challenge_recall:" "$STATE_DIR/latest-context.md" 2>/dev/null; then
                echo "[$(timestamp)] challenge score captured; recording scored run ID"
                echo "$completed_run_id" > "$STATE_DIR/last-scored-run-id"
                # Signal to post-cycle that THIS cycle scored a run.
                touch "$LOGS_DIR/scored-this-cycle"
            else
                echo "[$(timestamp)] challenge score NOT captured (api_error or missing); will retry next cycle" >&2
            fi
        fi
        ;;
    *)
        OBSERVATION_WAIT="${OPENCLAW_OBSERVATION_SECONDS:-300}"
        if (( OBSERVATION_WAIT > 0 )); then
            echo "[$(timestamp)] waiting ${OBSERVATION_WAIT}s for runs to mature before building context..."
            sleep "$OBSERVATION_WAIT"
        fi
        echo "[$(timestamp)] building latest run context after observation window..."
        "$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"
        ;;
esac

cp "$PROMPTS_DIR/scan-optimizer-loop.txt" "$STATE_DIR/openclaw-prompt.txt"
append_benchmark_context "$STATE_DIR/openclaw-prompt.txt"

echo "[$(timestamp)] prepared OpenClaw cycle inputs:"
echo "- context: $STATE_DIR/latest-context.md"
echo "- prompt:  $STATE_DIR/openclaw-prompt.txt"
