#!/usr/bin/env bash
# audit_orchestrator_api.sh — probe every Orchestrator REST endpoint and write findings
# Usage: bash audit_orchestrator_api.sh <cycle_id>
#
# Output: local-hermes-agent/audit-reports/<cycle_id>/api.json
# Exit code: 0 always (findings are encoded in the JSON; this script does not fail hard)

set -euo pipefail
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CYCLE_ID="${1:?Usage: audit_orchestrator_api.sh <cycle_id>}"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/audit_finding.sh"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
AUDIT_DIR="$ROOT_DIR/audit-reports/$CYCLE_ID"
export REPORT_PATH="$AUDIT_DIR/api.json"

mkdir -p "$AUDIT_DIR"
audit_init_report "$CYCLE_ID" "api"

# Resolve the bearer token once at startup.
# orchestrator_auth.sh's ensure_orchestrator_token uses BASH_SOURCE internally
# and can fail inside $() subshells; we call it here at the top-level scope.
# If it fails (e.g. DB not reachable), fall back to ORCH_TOKEN from env/scheduler.env.
_resolve_token_for_audit() {
    # Already have a token in env?
    if [[ -n "${ORCH_TOKEN:-}" ]]; then
        echo "${ORCH_TOKEN}"
        return 0
    fi
    # Try the scheduler env file directly
    local env_file="${LOCAL_HERMES_ENV_FILE:-$ROOT_DIR/state/scheduler.env}"
    if [[ -f "$env_file" ]]; then
        local tok
        tok="$(grep -m1 '^ORCH_TOKEN=' "$env_file" 2>/dev/null | cut -d= -f2-)"
        if [[ -n "$tok" ]]; then
            echo "$tok"
            return 0
        fi
    fi
    # Last resort: try ensure_orchestrator_token (may fail in subshells)
    if ensure_orchestrator_token 2>/dev/null; then
        echo "${ORCH_TOKEN:-}"
        return 0
    fi
    echo ""
    return 1
}

_RESOLVED_TOKEN="$(_resolve_token_for_audit || true)"
export _RESOLVED_TOKEN
if [[ -z "$_RESOLVED_TOKEN" ]]; then
    echo "[audit_orchestrator_api] ERROR: could not resolve ORCH_TOKEN" >&2
fi

# --- helpers ---------------------------------------------------------------

_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

_curl_authed() {
    # _curl_authed <method> <path> [<body_json>]
    # Runs curl with auth; returns (stdout=body, stderr=suppressed).
    # Bash 3.2 compatible — avoids empty array expansion under set -u.
    local method="$1" path="$2" body="${3:-}"
    if [[ -n "$body" ]]; then
        curl -sS -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null
    else
        curl -sS -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null
    fi
}

_curl_authed_code() {
    # Returns HTTP status code only; body discarded.
    local method="$1" path="$2" body="${3:-}"
    local tmp
    tmp="$(mktemp)"
    local code
    if [[ -n "$body" ]]; then
        set +e
        code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null)"
        set -e
    else
        set +e
        code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null)"
        set -e
    fi
    rm -f "$tmp"
    printf '%s' "${code:-000}"
}

_http() {
    # _http <method> <path> [<body_json>]
    # Returns: prints response body to stdout; exit code = 0 on 2xx, 1 otherwise.
    local method="$1" path="$2" body="${3:-}"
    local tmp http_code body_out
    tmp="$(mktemp)"

    set +e
    if [[ -n "$body" ]]; then
        http_code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null)"
    else
        http_code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $_RESOLVED_TOKEN" \
            "${ORCH_BASE_URL}${path}" 2>/dev/null)"
    fi
    local curl_exit=$?
    set -e

    if [[ $curl_exit -ne 0 ]]; then
        rm -f "$tmp"
        printf ''
        return 1
    fi

    body_out="$(cat "$tmp" 2>/dev/null || true)"
    rm -f "$tmp"
    printf '%s' "$body_out"
    if [[ "$http_code" =~ ^2 ]]; then return 0; fi
    return 1
}

_http_code() {
    # Returns only the HTTP status code string
    local method="$1" path="$2" body="${3:-}"
    printf '%s' "$(_curl_authed_code "$method" "$path" "$body")"
}

_http_unauth_code() {
    local method="$1" path="$2"
    local tmp http_code
    tmp="$(mktemp)"
    set +e
    http_code="$(curl -sS -o "$tmp" -w '%{http_code}' \
        -X "$method" \
        "${ORCH_BASE_URL}${path}" 2>/dev/null)"
    local curl_exit=$?
    set -e
    rm -f "$tmp"
    if [[ $curl_exit -ne 0 ]]; then echo "000"; return 0; fi
    printf '%s' "${http_code:-000}"
}

check_2xx() {
    local label="$1" method="$2" path="$3" body="${4:-}"
    local response code
    if response="$(_http "$method" "$path" "$body" 2>&1)"; then
        audit_record_pass
        echo "[PASS] $label → $method $path" >&2
        printf '%s' "$response"
    else
        local fnd_id
        fnd_id="$(audit_next_id "API")"
        code="$(_http_code "$method" "$path" "$body" 2>/dev/null || echo "000")"
        audit_append_finding "$fnd_id" "high" "orch_api" \
            "$label: $method $path returned non-2xx ($code)" \
            "{\"endpoint\": \"$method $path\", \"http_code\": \"$code\"}"
        echo "[FAIL] $label → $method $path (HTTP $code)" >&2
        printf ''
    fi
}

check_401() {
    local label="$1" method="$2" path="$3"
    local code
    code="$(_http_unauth_code "$method" "$path")"
    if [[ "$code" == "401" ]]; then
        audit_record_pass
        echo "[PASS] $label unauth check → $method $path (401)" >&2
    else
        local fnd_id
        fnd_id="$(audit_next_id "API")"
        audit_append_finding "$fnd_id" "high" "orch_api" \
            "$label: $method $path with no auth returned $code instead of 401" \
            "{\"endpoint\": \"$method $path\", \"http_code\": \"$code\", \"expected\": \"401\"}"
        echo "[FAIL] $label unauth → $method $path (got $code, expected 401)" >&2
    fi
}

check_404() {
    local label="$1" method="$2" path="$3" body="${4:-}"
    local code
    code="$(_http_code "$method" "$path" "$body" 2>/dev/null || echo "000")"
    if [[ "$code" == "404" ]]; then
        audit_record_pass
        echo "[PASS] $label 404 check → $method $path" >&2
    else
        local fnd_id
        fnd_id="$(audit_next_id "API")"
        audit_append_finding "$fnd_id" "medium" "orch_api" \
            "$label: $method $path with nonexistent id returned $code instead of 404" \
            "{\"endpoint\": \"$method $path\", \"http_code\": \"$code\", \"expected\": \"404\"}"
        echo "[FAIL] $label 404 check → $method $path (got $code, expected 404)" >&2
    fi
}

check_keys() {
    local label="$1" json="$2" keys_csv="$3"
    if [[ -z "$json" ]]; then
        echo "[SKIP] $label key check — no response body" >&2
        return
    fi
    IFS=',' read -ra keys <<< "$keys_csv"
    local missing=()
    for key in "${keys[@]}"; do
        if ! printf '%s' "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); assert '$key' in d" 2>/dev/null; then
            missing+=("$key")
        fi
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        audit_record_pass
        echo "[PASS] $label keys: $keys_csv" >&2
    else
        local fnd_id
        fnd_id="$(audit_next_id "API")"
        audit_append_finding "$fnd_id" "medium" "orch_api" \
            "$label: response missing keys: ${missing[*]}" \
            "{\"endpoint\": \"$label\", \"missing_keys\": [$(printf '"%s",' "${missing[@]}" | sed 's/,$//')]}"
        echo "[FAIL] $label missing keys: ${missing[*]}" >&2
    fi
}

# --- preflight: check orchestrator is up ------------------------------------

if ! curl -fsSL "$ORCH_BASE_URL/healthz" >/dev/null 2>&1; then
    # Try /auth/me as a proxy for liveness
    if ! _http "GET" "/auth/me" >/dev/null 2>&1; then
        audit_append_finding "API-000" "critical" "orch_api" \
            "Orchestrator unreachable at $ORCH_BASE_URL" \
            "{\"url\": \"$ORCH_BASE_URL\", \"checked_at\": \"$(_now)\"}"
        audit_finalize_report
        echo "[BLOCKED] orchestrator unreachable; aborting API audit" >&2
        exit 0
    fi
fi

# --- preflight: verify ORCH_TOKEN is valid ---------------------------------
# If it's stale (orchestrator restarted, session table wiped, token rotated,
# etc.) every authed probe below will just re-emit 401 as a false "product
# bug". Short-circuit with one sentinel finding so the operator knows to
# rotate the token instead of chasing phantom API failures. Verified
# necessary after cycle 20260423T023057Z produced 4 false 401 findings
# because the token in scheduler.env had been rotated after the last cycle.

auth_probe_code="$(_curl_authed_code "GET" "/auth/me")"
if [[ "$auth_probe_code" != "200" ]]; then
    # A stale scheduler token is recoverable: refresh from the orchestrator DB,
    # update scheduler.env, and retry once before emitting a sentinel finding.
    # This keeps normal post-restart cycles from reporting false critical API
    # failures that disappear as soon as the token is rotated.
    if ensure_orchestrator_token 2>/dev/null; then
        _RESOLVED_TOKEN="${ORCH_TOKEN:-}"
        export _RESOLVED_TOKEN
        auth_probe_code="$(_curl_authed_code "GET" "/auth/me")"
    fi
fi
if [[ "$auth_probe_code" != "200" ]]; then
    if [[ -z "$_RESOLVED_TOKEN" ]]; then
        reason="ORCH_TOKEN could not be resolved from env or scheduler.env"
    else
        reason="ORCH_TOKEN rejected by /auth/me (HTTP $auth_probe_code) after refresh attempt; scheduler token may be unrecoverable"
    fi
    audit_append_finding "API-AUTH" "critical" "orch_api" \
        "$reason" \
        "{\"endpoint\": \"GET /auth/me\", \"http_code\": \"$auth_probe_code\", \"hint\": \"ensure_orchestrator_token failed to refresh a valid scheduler token\"}"
    audit_finalize_report
    echo "[BLOCKED] $reason; aborting API audit to avoid 401-noise findings" >&2
    exit 0
fi

# --- GET /auth/me -----------------------------------------------------------

me_json="$(check_2xx "auth_me" "GET" "/auth/me" || true)"
check_401 "auth_me" "GET" "/auth/me"
check_keys "auth_me" "$me_json" "id,username"

# --- Project CRUD -----------------------------------------------------------

# Create throwaway test project
create_proj_body='{"name":"__audit-test-project__","provider_id":"","model_id":"","api_key":"","base_url":"","crawler_json":"{\"KATANA_CRAWL_DEPTH\":7}","parallel_json":"{}","agents_json":"{\"fuzzer\":false}"}'

proj_resp="$(check_2xx "projects_create" "POST" "/projects" "$create_proj_body" || true)"
check_401 "projects_create" "POST" "/projects"

test_project_id=""
if [[ -n "$proj_resp" ]]; then
    test_project_id="$(printf '%s' "$proj_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
    check_keys "projects_create" "$proj_resp" "id,name,slug,crawler_json,parallel_json,agents_json"
fi

# GET /projects
list_resp="$(check_2xx "projects_list" "GET" "/projects" || true)"
check_401 "projects_list" "GET" "/projects"

# PATCH /projects/{id} — only if we created one
if [[ -n "$test_project_id" ]]; then
    patch_resp="$(check_2xx "projects_patch" "PATCH" "/projects/$test_project_id" '{"name":"__audit-test-patched__"}' || true)"
    check_401 "projects_patch" "PATCH" "/projects/$test_project_id"
    check_keys "projects_patch" "$patch_resp" "id,name"
fi

# 404 for nonexistent project
check_404 "projects_get_404" "GET" "/projects/999999999"

# --- Run CRUD ---------------------------------------------------------------

test_run_id=""
if [[ -n "$test_project_id" ]]; then
    run_resp="$(check_2xx "runs_create" "POST" "/projects/$test_project_id/runs" '{"target":"http://127.0.0.1:8000"}' || true)"
    check_401 "runs_create" "POST" "/projects/$test_project_id/runs"
    if [[ -n "$run_resp" ]]; then
        test_run_id="$(printf '%s' "$run_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
        check_keys "runs_create" "$run_resp" "id,target,status,engagement_root,created_at,updated_at"
    fi

    # GET runs list
    runs_list_resp="$(check_2xx "runs_list" "GET" "/projects/$test_project_id/runs" || true)"
    check_401 "runs_list" "GET" "/projects/$test_project_id/runs"

    # 404 for nonexistent run
    check_404 "runs_get_404" "GET" "/projects/$test_project_id/runs/999999999/summary"

    if [[ -n "$test_run_id" ]]; then
        # GET summary
        summary_resp="$(check_2xx "runs_summary" "GET" "/projects/$test_project_id/runs/$test_run_id/summary" || true)"
        check_keys "runs_summary" "$summary_resp" "target,overview,coverage,phases,agents,dispatches,cases"

        # GET sub-resources
        check_2xx "runs_cases" "GET" "/projects/$test_project_id/runs/$test_run_id/cases" >/dev/null || true
        check_2xx "runs_dispatches" "GET" "/projects/$test_project_id/runs/$test_run_id/dispatches" >/dev/null || true
        check_2xx "runs_documents" "GET" "/projects/$test_project_id/runs/$test_run_id/documents" >/dev/null || true
        check_2xx "runs_events" "GET" "/projects/$test_project_id/runs/$test_run_id/events" >/dev/null || true

        # POST /status stop — only for our throwaway test run
        stop_resp="$(check_2xx "runs_stop" "POST" "/projects/$test_project_id/runs/$test_run_id/status" '{"status":"stopped"}' || true)"
        check_keys "runs_stop" "$stop_resp" "id,status"

        # DELETE run
        del_run_code="$(_http_code "DELETE" "/projects/$test_project_id/runs/$test_run_id")"
        if [[ "$del_run_code" == "204" ]]; then
            audit_record_pass
            echo "[PASS] runs_delete → DELETE /projects/$test_project_id/runs/$test_run_id (204)" >&2
            # Verify 404 after delete
            check_404 "runs_delete_verify_404" "GET" "/projects/$test_project_id/runs/$test_run_id/summary"
        else
            fnd_id="$(audit_next_id "API")"
            audit_append_finding "$fnd_id" "medium" "orch_api" \
                "runs_delete: DELETE returned $del_run_code instead of 204" \
                "{\"endpoint\": \"DELETE /projects/$test_project_id/runs/$test_run_id\", \"http_code\": \"$del_run_code\"}"
            echo "[FAIL] runs_delete → got $del_run_code expected 204" >&2
        fi
    fi

    # DELETE project
    del_proj_code="$(_http_code "DELETE" "/projects/$test_project_id")"
    if [[ "$del_proj_code" == "204" ]]; then
        audit_record_pass
        echo "[PASS] projects_delete → DELETE /projects/$test_project_id (204)" >&2
        check_404 "projects_delete_verify_404" "GET" "/projects/$test_project_id"
    else
        fnd_id="$(audit_next_id "API")"
        audit_append_finding "$fnd_id" "medium" "orch_api" \
            "projects_delete: DELETE returned $del_proj_code instead of 204" \
            "{\"endpoint\": \"DELETE /projects/$test_project_id\", \"http_code\": \"$del_proj_code\"}"
        echo "[FAIL] projects_delete → got $del_proj_code expected 204" >&2
    fi
fi

# --- finalize ---------------------------------------------------------------

audit_finalize_report
echo "[audit_orchestrator_api] complete: pass=$_AUDIT_PASS_COUNT fail=$_AUDIT_FAIL_COUNT → $REPORT_PATH" >&2
