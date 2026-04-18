#!/bin/bash
# scripts/lib/container.sh — Container execution layer for pentest tools
# Source this file: . scripts/lib/container.sh

CONTAINER_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$CONTAINER_LIB_DIR/processes.sh"
# shellcheck source=/dev/null
. "$CONTAINER_LIB_DIR/noise.sh"

REDTEAM_IMAGE="${REDTEAM_IMAGE:-kali-redteam:latest}"
PROXY_IMAGE="${PROXY_IMAGE:-redteam-proxy:latest}"
KATANA_IMAGE="${KATANA_IMAGE:-projectdiscovery/katana:latest}"
MITMPROXY_BIN="${MITMPROXY_BIN:-mitmdump}"
KATANA_LOCAL_BIN="${KATANA_LOCAL_BIN:-katana}"
KATANA_CHROME_BIN="${KATANA_CHROME_BIN:-/usr/bin/chromium}"
KATANA_HEADLESS_OPTIONS="${KATANA_HEADLESS_OPTIONS:---no-sandbox,--disable-dev-shm-usage,--disable-gpu}"
KATANA_CRAWL_DEPTH="${KATANA_CRAWL_DEPTH:-8}"
KATANA_CRAWL_DURATION="${KATANA_CRAWL_DURATION:-15m}"
KATANA_TIMEOUT_SECONDS="${KATANA_TIMEOUT_SECONDS:-20}"
KATANA_TIME_STABLE_SECONDS="${KATANA_TIME_STABLE_SECONDS:-5}"
KATANA_RETRY_COUNT="${KATANA_RETRY_COUNT:-3}"
KATANA_MAX_FAILURE_COUNT="${KATANA_MAX_FAILURE_COUNT:-20}"
KATANA_CONCURRENCY="${KATANA_CONCURRENCY:-15}"
KATANA_PARALLELISM="${KATANA_PARALLELISM:-4}"
KATANA_RATE_LIMIT="${KATANA_RATE_LIMIT:-60}"
KATANA_STRATEGY="${KATANA_STRATEGY:-breadth-first}"
KATANA_ENABLE_JSLUICE="${KATANA_ENABLE_JSLUICE:-0}"
KATANA_ENABLE_PATH_CLIMB="${KATANA_ENABLE_PATH_CLIMB:-0}"
KATANA_ENABLE_HYBRID="${KATANA_ENABLE_HYBRID:-1}"
KATANA_ENABLE_XHR="${KATANA_ENABLE_XHR:-1}"
KATANA_ENABLE_HEADLESS="${KATANA_ENABLE_HEADLESS:-1}"
HOST_GATEWAY_ALIAS="${HOST_GATEWAY_ALIAS:-host.docker.internal}"

runtime_mode() {
    echo "${REDTEAM_RUNTIME_MODE:-docker}"
}

_is_loopback_host() {
    local host="${1:-}"
    case "$host" in
        localhost|127.0.0.1|0.0.0.0|::1|"[::1]")
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_scope_uses_loopback_target() {
    _resolve_engagement_dir || return 1
    local scope_file="${ENGAGEMENT_DIR_ABS}/scope.json"
    local hostname=""

    [[ -f "$scope_file" ]] || return 1
    hostname="$(jq -r '.hostname // empty' "$scope_file" 2>/dev/null || true)"
    [[ -n "$hostname" ]] || return 1
    _is_loopback_host "$hostname"
}

_rewrite_runtime_url() {
    local url="${1:-}"
    local alias_host="$HOST_GATEWAY_ALIAS"
    local prefix rest auth hostport suffix host port rebuilt

    if ! _scope_uses_loopback_target; then
        printf '%s\n' "$url"
        return 0
    fi

    case "$url" in
        http://*|https://*)
            ;;
        *)
            printf '%s\n' "$url"
            return 0
            ;;
    esac

    prefix="${url%%://*}://"
    rest="${url#"$prefix"}"
    auth=""
    if [[ "$rest" == *@* ]]; then
        auth="${rest%%@*}@"
        rest="${rest#*@}"
    fi

    hostport="${rest%%[/?#]*}"
    suffix="${rest#"$hostport"}"

    if [[ "$hostport" == \[*\]* ]]; then
        host="${hostport%%]*}"
        host="${host#[}"
        port="${hostport#"]"}"
    else
        host="${hostport%%:*}"
        port="${hostport#"$host"}"
    fi

    if ! _is_loopback_host "$host"; then
        printf '%s\n' "$url"
        return 0
    fi

    rebuilt="${prefix}${auth}${alias_host}${port}${suffix}"
    printf '%s\n' "$rebuilt"
}

_rewrite_runtime_target_arg() {
    local arg="${1:-}"

    if ! _scope_uses_loopback_target; then
        printf '%s\n' "$arg"
        return 0
    fi

    case "$arg" in
        http://*|https://*)
            _rewrite_runtime_url "$arg"
            ;;
        localhost|127.0.0.1|0.0.0.0|::1|"[::1]")
            printf '%s\n' "$HOST_GATEWAY_ALIAS"
            ;;
        *)
            printf '%s\n' "$arg"
            ;;
    esac
}

_rewrite_runtime_args() {
    local arg
    for arg in "$@"; do
        printf '%s\0' "$(_rewrite_runtime_target_arg "$arg")"
    done
}

# Resolve ENGAGEMENT_DIR to absolute path (Docker requires absolute paths for -v mounts)
# Usage: _resolve_engagement_dir
# Sets ENGAGEMENT_DIR_ABS
_resolve_engagement_dir() {
    if [ -z "$ENGAGEMENT_DIR" ]; then
        echo "ERROR: ENGAGEMENT_DIR not set" >&2
        return 1
    fi
    # Convert relative to absolute
    if [[ "$ENGAGEMENT_DIR" = /* ]]; then
        ENGAGEMENT_DIR_ABS="$ENGAGEMENT_DIR"
    else
        ENGAGEMENT_DIR_ABS="$(cd "$ENGAGEMENT_DIR" 2>/dev/null && pwd || echo "$(pwd)/$ENGAGEMENT_DIR")"
    fi
}

_engagement_slug() {
    _resolve_engagement_dir || return 1
    basename "$ENGAGEMENT_DIR_ABS" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9._-' '-'
}

_proxy_container_name() {
    local slug
    slug="$(_engagement_slug)" || return 1
    echo "redteam-proxy-${slug}"
}

_katana_container_name() {
    local slug
    slug="$(_engagement_slug)" || return 1
    echo "redteam-katana-${slug}"
}

_auth_header_args() {
    _resolve_engagement_dir || return 1
    local auth_file="${ENGAGEMENT_DIR_ABS}/auth.json"
    if [ ! -f "$auth_file" ]; then
        return 0
    fi

    jq -r '
      [
        (if (.cookies | type) == "object" and ((.cookies | keys | length) > 0)
         then "Cookie: " + (.cookies | to_entries | map(.key + "=" + .value) | join("; "))
         else empty end),
        (if (.headers | type) == "object"
         then (.headers | to_entries[] | .key + ": " + .value)
         else empty end)
      ] | .[]
    ' "$auth_file" 2>/dev/null | while IFS= read -r header; do
        [ -n "$header" ] || continue
        printf '%s\0%s\0' "-H" "$header"
    done
}

_auth_header_array() {
    local args=()
    while IFS= read -r -d '' item; do
        args+=("$item")
    done < <(_auth_header_args)
    if [ ${#args[@]} -gt 0 ]; then
        printf '%s\n' "${args[@]}"
    fi
}

_engagement_env_file() {
    _resolve_engagement_dir || return 1
    if [ -f "${ENGAGEMENT_DIR_ABS}/.env" ]; then
        echo "${ENGAGEMENT_DIR_ABS}/.env"
    elif [ -f "$(pwd)/.env" ]; then
        echo "$(pwd)/.env"
    fi
}

_regex_escape() {
    printf '%s' "$1" | sed -e 's/[.[\*^$()+?{}|\\/]/\\&/g'
}

_katana_scope_args() {
    _resolve_engagement_dir || return 1
    local scope_file="${ENGAGEMENT_DIR_ABS}/scope.json"
    local patterns=()
    local entry host escaped

    if [[ ! -f "$scope_file" ]]; then
        return 0
    fi

    while IFS= read -r entry; do
        [[ -n "$entry" ]] || continue
        if [[ "$entry" == \*.* ]]; then
            host="${entry#*.}"
            escaped="$(_regex_escape "$host")"
            patterns+=("^https?://([^.]+\\.)*${escaped}([/:?#]|$)")
        else
            escaped="$(_regex_escape "$entry")"
            patterns+=("^https?://${escaped}([/:?#]|$)")
        fi
    done < <(jq -r '[.hostname // empty, (.scope // [] | .[])] | map(select(type == "string" and length > 0)) | unique[]' "$scope_file" 2>/dev/null)

    if _scope_uses_loopback_target; then
        escaped="$(_regex_escape "$HOST_GATEWAY_ALIAS")"
        patterns+=("^https?://${escaped}([/:?#]|$)")
    fi

    if [[ ${#patterns[@]} -eq 0 ]]; then
        return 0
    fi

    local pattern
    for pattern in "${patterns[@]}"; do
        printf '%s\0%s\0' "-cs" "$pattern"
    done
}

_katana_scope_array() {
    local args=()
    while IFS= read -r -d '' item; do
        args+=("$item")
    done < <(_katana_scope_args)
    if [[ ${#args[@]} -gt 0 ]]; then
        printf '%s\n' "${args[@]}"
    fi
}

_load_engagement_env() {
    local env_file
    env_file="$(_engagement_env_file)"
    if [ -n "$env_file" ] && [ -f "$env_file" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
}

_pid_file() {
    _resolve_engagement_dir || return 1
    mkdir -p "${ENGAGEMENT_DIR_ABS}/pids"
    echo "${ENGAGEMENT_DIR_ABS}/pids/$1.pid"
}

_engagement_pid_dir() {
    _resolve_engagement_dir || return 1
    mkdir -p "${ENGAGEMENT_DIR_ABS}/pids"
    echo "${ENGAGEMENT_DIR_ABS}/pids"
}

_start_local_process() {
    local name="$1"; shift
    local pid_dir
    local env_file
    local expected_command
    pid_dir="$(_engagement_pid_dir)" || return 1
    env_file="$(_engagement_env_file)"
    expected_command="$(basename "$1")"
    start_managed_process "$pid_dir" "$name" "$expected_command" env \
        ENGAGEMENT_DIR_ABS="$ENGAGEMENT_DIR_ABS" \
        ENGAGEMENT_DIR="$ENGAGEMENT_DIR_ABS" \
        REDTEAM_ENV_FILE="$env_file" \
        bash -lc '
        cd "$ENGAGEMENT_DIR_ABS"
        if [ -n "${REDTEAM_ENV_FILE:-}" ] && [ -f "$REDTEAM_ENV_FILE" ]; then
            set -a
            . "$REDTEAM_ENV_FILE"
            set +a
        fi
        "$@"
    ' bash "$@"
}

_stop_local_process() {
    local name="$1"
    local expected_command="${2:-}"
    local pid_dir
    pid_dir="$(_engagement_pid_dir)" || return 1
    stop_managed_process "$pid_dir" "$name" "$expected_command"
}

# Run a one-shot tool in the kali-redteam container
# Usage: run_tool <tool> [args...]
# Requires: ENGAGEMENT_DIR env var set
run_tool() {
    local tool="$1"; shift
    _resolve_engagement_dir || return 1
    local runtime_args=()
    while IFS= read -r -d '' item; do
        runtime_args+=("$item")
    done < <(_rewrite_runtime_args "$@")
    if [ "$(runtime_mode)" = "local" ]; then
        (
            cd "$ENGAGEMENT_DIR_ABS"
            export ENGAGEMENT_DIR="$ENGAGEMENT_DIR_ABS"
            _load_engagement_env
            if [[ "$tool" == "curl" && -x "${ENGAGEMENT_DIR_ABS}/tools/rtcurl" ]]; then
                "${ENGAGEMENT_DIR_ABS}/tools/rtcurl" "${runtime_args[@]}"
            else
                "$tool" "${runtime_args[@]}"
            fi
        )
        return
    fi
    # Build docker args array to avoid word-splitting issues
    local docker_args=(--rm --network host -v "${ENGAGEMENT_DIR_ABS}:/engagement" -w /engagement)
    # Mount .env file if it exists (provides API keys for subfinder, nuclei, etc.)
    if [ -f "${ENGAGEMENT_DIR_ABS}/.env" ]; then
        docker_args+=(--env-file "${ENGAGEMENT_DIR_ABS}/.env")
    elif [ -f "$(pwd)/.env" ]; then
        docker_args+=(--env-file "$(pwd)/.env")
    fi
    if [[ "$tool" == "curl" && -x "${ENGAGEMENT_DIR_ABS}/tools/rtcurl" ]]; then
        docker run "${docker_args[@]}" "$REDTEAM_IMAGE" /engagement/tools/rtcurl "${runtime_args[@]}"
        return
    fi
    docker run "${docker_args[@]}" "$REDTEAM_IMAGE" "$tool" "${runtime_args[@]}"
}

# Start the mitmproxy container (persistent)
# Usage: start_proxy [extra_mitmdump_args...]
start_proxy() {
    _resolve_engagement_dir || return 1
    if [ "$(runtime_mode)" = "local" ]; then
        mkdir -p "${ENGAGEMENT_DIR_ABS}/scans"
        _start_local_process proxy "$MITMPROXY_BIN" --set engagement_dir="$ENGAGEMENT_DIR_ABS" "$@"
        echo "[proxy] Started on port ${MITMPROXY_PORT:-8080}"
        return 0
    fi
    local container_name
    container_name="$(_proxy_container_name)" || return 1
    if docker ps --format '{{.Names}}' | grep -q "^${container_name}\$"; then
        echo "[proxy] Already running"
        return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}\$"; then
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi
    docker run -d --name "$container_name" \
        --network host \
        -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
        "$PROXY_IMAGE" \
        --set engagement_dir=/engagement "$@"
    echo "[proxy] Started on port 8080"
    echo "[proxy] Configure browser proxy: http://127.0.0.1:8080"
}

# Stop the mitmproxy container (also removes exited containers to avoid name conflicts)
stop_proxy() {
    if [ "$(runtime_mode)" = "local" ]; then
        _stop_local_process proxy "$MITMPROXY_BIN"
        return 0
    fi
    local container_name
    container_name="$(_proxy_container_name)" || return 0
    docker stop "$container_name" 2>/dev/null
    docker rm -f "$container_name" 2>/dev/null
    echo "[proxy] Stopped and removed"
}

# Start Katana crawler container (persistent)
# Usage: start_katana <target_url> [extra_katana_args...]
start_katana() {
    local target="$1"; shift
    _resolve_engagement_dir || return 1
    local runtime_target
    runtime_target="$(_rewrite_runtime_target_arg "$target")"
    local katana_args=(
        -u "$runtime_target"
        -kf all
        -iqp
        -fsu
        -ns
        -s "$KATANA_STRATEGY"
        -d "$KATANA_CRAWL_DEPTH"
        -ct "$KATANA_CRAWL_DURATION"
        -timeout "$KATANA_TIMEOUT_SECONDS"
        -time-stable "$KATANA_TIME_STABLE_SECONDS"
        -retry "$KATANA_RETRY_COUNT"
        -mfc "$KATANA_MAX_FAILURE_COUNT"
        -c "$KATANA_CONCURRENCY"
        -p "$KATANA_PARALLELISM"
        -rl "$KATANA_RATE_LIMIT"
        -mrs 16777216
        -omit-raw
        -omit-body
        -jsonl
        -silent
    )
    if [[ "${KATANA_ENABLE_HYBRID}" == "1" ]]; then
        katana_args+=(-hh -jc -fx -td -tlsi -duc)
    fi
    if [[ "${KATANA_ENABLE_XHR}" == "1" ]]; then
        katana_args+=(-xhr -xhr-extraction)
    fi
    if [[ "${KATANA_ENABLE_HEADLESS}" == "1" ]]; then
        if [[ "${KATANA_ENABLE_HYBRID}" != "1" ]]; then
            katana_args+=(-hl)
        fi
        katana_args+=(
            -system-chrome
            -system-chrome-path "$KATANA_CHROME_BIN"
            -headless-options "$KATANA_HEADLESS_OPTIONS"
        )
    fi
    if [[ "${KATANA_ENABLE_JSLUICE}" == "1" ]]; then
        katana_args+=(-jsl)
    fi
    if [[ "${KATANA_ENABLE_PATH_CLIMB}" == "1" ]]; then
        katana_args+=(-pc)
    fi
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        katana_args+=(-cos "$line")
    done < <(katana_emit_out_of_scope_regexes)
    if [ "$(runtime_mode)" = "local" ]; then
        if [ -z "$target" ]; then
            echo "ERROR: target URL required" >&2
            return 1
        fi
        mkdir -p "${ENGAGEMENT_DIR_ABS}/scans" "${ENGAGEMENT_DIR_ABS}/pids"
        local katana_output_path="${KATANA_OUTPUT_PATH:-${ENGAGEMENT_DIR_ABS}/scans/katana_output.jsonl}"
        local auth_args=()
        local scope_args=()
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            auth_args+=("$line")
        done < <(_auth_header_array)
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            scope_args+=("$line")
        done < <(_katana_scope_array)
        _start_local_process katana "$KATANA_LOCAL_BIN" "${katana_args[@]}" "${scope_args[@]+"${scope_args[@]}"}" "${auth_args[@]+"${auth_args[@]}"}" -elog "${ENGAGEMENT_DIR_ABS}/scans/katana_error.log" -o "$katana_output_path" "$@"
        echo "[katana] Started crawling $target"
        return 0
    fi
    local container_name
    container_name="$(_katana_container_name)" || return 1
    if [ -z "$target" ]; then
        echo "ERROR: target URL required" >&2
        return 1
    fi

    if docker ps --format '{{.Names}}' | grep -q "^${container_name}\$"; then
        echo "[katana] Already running"
        return 0
    fi

    # Remove stale stopped container to avoid name conflicts on restart.
    if docker ps -a --format '{{.Names}}' | grep -q "^${container_name}\$"; then
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi

    local auth_args=()
    local scope_args=()
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        auth_args+=("$line")
    done < <(_auth_header_array)
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        scope_args+=("$line")
    done < <(_katana_scope_array)

    mkdir -p "${ENGAGEMENT_DIR_ABS}/scans" "${ENGAGEMENT_DIR_ABS}/pids"
    local katana_output_path="${KATANA_OUTPUT_PATH:-/engagement/scans/katana_output.jsonl}"
    if [[ -n "${KATANA_OUTPUT_PATH:-}" ]] && [[ "$katana_output_path" == "$ENGAGEMENT_DIR_ABS"/* ]]; then
        katana_output_path="/engagement/${katana_output_path#${ENGAGEMENT_DIR_ABS}/}"
    fi

    docker run -d --name "$container_name" \
        --network host \
        -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
        "$KATANA_IMAGE" \
        "${katana_args[@]}" \
        "${scope_args[@]+"${scope_args[@]}"}" \
        "${auth_args[@]+"${auth_args[@]}"}" \
        -elog /engagement/scans/katana_error.log \
        -o "$katana_output_path"
    echo "[katana] Started crawling $target"
}

# Stop Katana container (also removes exited containers to avoid name conflicts)
stop_katana() {
    if [ "$(runtime_mode)" = "local" ]; then
        _stop_local_process katana "$KATANA_LOCAL_BIN"
        return 0
    fi
    local container_name
    container_name="$(_katana_container_name)" || return 0
    docker stop "$container_name" 2>/dev/null
    docker rm -f "$container_name" 2>/dev/null
    echo "[katana] Stopped and removed"
}

# Stop all engagement containers
stop_all_containers() {
    stop_proxy
    stop_katana
    echo "[containers] Current engagement containers stopped"
}

# Check if required Docker images are built
# Returns 0 if all present, 1 if any missing
check_images() {
    if [ "$(runtime_mode)" = "local" ]; then
        echo "[OK] local runtime bundles required tools"
        return 0
    fi
    local all_ok=true
    for img in "$REDTEAM_IMAGE" "$PROXY_IMAGE" "$KATANA_IMAGE"; do
        if docker image inspect "$img" >/dev/null 2>&1; then
            echo "[OK] $img"
        else
            echo "[MISSING] $img"
            all_ok=false
        fi
    done
    if [ "$all_ok" = false ]; then
        echo ""
        echo "Build missing images: cd docker && docker compose build"
        return 1
    fi
    return 0
}

# Check if Docker is available and running
check_docker() {
    if [ "$(runtime_mode)" = "local" ]; then
        echo "[OK] local runtime mode active"
        return 0
    fi
    if ! which docker >/dev/null 2>&1; then
        echo "ERROR: Docker is not installed" >&2
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "ERROR: Docker daemon is not running" >&2
        return 1
    fi
    echo "[OK] Docker is available"
    return 0
}
