#!/bin/bash
# scripts/lib/container.sh — Container execution layer for pentest tools
# Source this file: . scripts/lib/container.sh

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/processes.sh"

REDTEAM_IMAGE="${REDTEAM_IMAGE:-kali-redteam:latest}"
PROXY_IMAGE="${PROXY_IMAGE:-redteam-proxy:latest}"
KATANA_IMAGE="${KATANA_IMAGE:-projectdiscovery/katana:latest}"
MITMPROXY_BIN="${MITMPROXY_BIN:-mitmdump}"
KATANA_LOCAL_BIN="${KATANA_LOCAL_BIN:-katana}"

runtime_mode() {
    echo "${REDTEAM_RUNTIME_MODE:-docker}"
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
    pid_dir="$(_engagement_pid_dir)" || return 1
    env_file="$(_engagement_env_file)"
    start_managed_process "$pid_dir" "$name" env \
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
    local pid_dir
    pid_dir="$(_engagement_pid_dir)" || return 1
    stop_managed_process "$pid_dir" "$name"
}

# Run a one-shot tool in the kali-redteam container
# Usage: run_tool <tool> [args...]
# Requires: ENGAGEMENT_DIR env var set
run_tool() {
    local tool="$1"; shift
    _resolve_engagement_dir || return 1
    if [ "$(runtime_mode)" = "local" ]; then
        (
            cd "$ENGAGEMENT_DIR_ABS"
            export ENGAGEMENT_DIR="$ENGAGEMENT_DIR_ABS"
            _load_engagement_env
            if [[ "$tool" == "curl" && -x "${ENGAGEMENT_DIR_ABS}/tools/rtcurl" ]]; then
                "${ENGAGEMENT_DIR_ABS}/tools/rtcurl" "$@"
            else
                "$tool" "$@"
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
        docker run "${docker_args[@]}" "$REDTEAM_IMAGE" /engagement/tools/rtcurl "$@"
        return
    fi
    docker run "${docker_args[@]}" "$REDTEAM_IMAGE" "$tool" "$@"
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
        _stop_local_process proxy
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
    if [ "$(runtime_mode)" = "local" ]; then
        if [ -z "$target" ]; then
            echo "ERROR: target URL required" >&2
            return 1
        fi
        mkdir -p "${ENGAGEMENT_DIR_ABS}/scans"
        local auth_args=()
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            auth_args+=("$line")
        done < <(_auth_header_array)
        _start_local_process katana "$KATANA_LOCAL_BIN" -u "$target" -jc -d 3 -jsonl -silent "${auth_args[@]+"${auth_args[@]}"}" -o "${ENGAGEMENT_DIR_ABS}/scans/katana_output.jsonl" "$@"
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
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        auth_args+=("$line")
    done < <(_auth_header_array)

    mkdir -p "${ENGAGEMENT_DIR_ABS}/scans"

    docker run -d --name "$container_name" \
        --network host \
        -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
        "$KATANA_IMAGE" \
        -u "$target" -jc -d 3 -jsonl -silent \
        "${auth_args[@]}" \
        -o /engagement/scans/katana_output.jsonl
    echo "[katana] Started crawling $target"
}

# Stop Katana container (also removes exited containers to avoid name conflicts)
stop_katana() {
    if [ "$(runtime_mode)" = "local" ]; then
        _stop_local_process katana
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
