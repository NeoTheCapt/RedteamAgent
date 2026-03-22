#!/bin/bash
# scripts/lib/container.sh — Container execution layer for pentest tools
# Source this file: . scripts/lib/container.sh

REDTEAM_IMAGE="${REDTEAM_IMAGE:-kali-redteam:latest}"
PROXY_IMAGE="${PROXY_IMAGE:-redteam-proxy:latest}"
KATANA_IMAGE="${KATANA_IMAGE:-projectdiscovery/katana:latest}"

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

# Run a one-shot tool in the kali-redteam container
# Usage: run_tool <tool> [args...]
# Requires: ENGAGEMENT_DIR env var set
run_tool() {
    local tool="$1"; shift
    _resolve_engagement_dir || return 1
    # Build docker args array to avoid word-splitting issues
    local docker_args=(--rm --network host -v "${ENGAGEMENT_DIR_ABS}:/engagement" -w /engagement)
    # Mount .env file if it exists (provides API keys for subfinder, nuclei, etc.)
    if [ -f "${ENGAGEMENT_DIR_ABS}/.env" ]; then
        docker_args+=(--env-file "${ENGAGEMENT_DIR_ABS}/.env")
    elif [ -f "$(pwd)/.env" ]; then
        docker_args+=(--env-file "$(pwd)/.env")
    fi
    docker run "${docker_args[@]}" "$REDTEAM_IMAGE" "$tool" "$@"
}

# Start the mitmproxy container (persistent)
# Usage: start_proxy [extra_mitmdump_args...]
start_proxy() {
    _resolve_engagement_dir || return 1
    if docker ps --format '{{.Names}}' | grep -q '^redteam-proxy$'; then
        echo "[proxy] Already running"
        return 0
    fi
    docker run -d --name redteam-proxy \
        --network host \
        -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
        "$PROXY_IMAGE" \
        --set engagement_dir=/engagement "$@"
    echo "[proxy] Started on port 8080"
    echo "[proxy] Configure browser proxy: http://127.0.0.1:8080"
}

# Stop the mitmproxy container (also removes exited containers to avoid name conflicts)
stop_proxy() {
    docker stop redteam-proxy 2>/dev/null
    docker rm -f redteam-proxy 2>/dev/null
    echo "[proxy] Stopped and removed"
}

# Start Katana crawler container (persistent)
# Usage: start_katana <target_url> [extra_katana_args...]
start_katana() {
    local target="$1"; shift
    _resolve_engagement_dir || return 1
    if [ -z "$target" ]; then
        echo "ERROR: target URL required" >&2
        return 1
    fi

    if docker ps --format '{{.Names}}' | grep -q '^redteam-katana$'; then
        echo "[katana] Already running"
        return 0
    fi

    # Remove stale stopped container to avoid name conflicts on restart.
    if docker ps -a --format '{{.Names}}' | grep -q '^redteam-katana$'; then
        docker rm -f redteam-katana >/dev/null 2>&1 || true
    fi

    # Build cookie args from auth.json if available
    local cookie_flag=""
    local cookie_val=""
    if [ -f "${ENGAGEMENT_DIR_ABS}/auth.json" ]; then
        local cookies
        cookies=$(jq -r 'if .cookies | type == "object" then .cookies | to_entries | map(.key + "=" + .value) | join("; ") elif .cookies | type == "string" then .cookies else "" end' "${ENGAGEMENT_DIR_ABS}/auth.json" 2>/dev/null)
        if [ -n "$cookies" ] && [ "$cookies" != "null" ] && [ "$cookies" != "" ]; then
            cookie_flag="-H"
            cookie_val="Cookie: $cookies"
        fi
    fi

    mkdir -p "${ENGAGEMENT_DIR_ABS}/scans"

    # Note: avoid empty array expansion under set -u by using individual variables
    if [ -n "$cookie_flag" ]; then
        docker run -d --name redteam-katana \
            --network host \
            -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
            "$KATANA_IMAGE" \
            -u "$target" -jc -d 3 -jsonl -silent \
            "$cookie_flag" "$cookie_val" \
            -o /engagement/scans/katana_output.jsonl
    else
        docker run -d --name redteam-katana \
            --network host \
            -v "${ENGAGEMENT_DIR_ABS}:/engagement" \
            "$KATANA_IMAGE" \
            -u "$target" -jc -d 3 -jsonl -silent \
            -o /engagement/scans/katana_output.jsonl
    fi
    echo "[katana] Started crawling $target"
}

# Stop Katana container (also removes exited containers to avoid name conflicts)
stop_katana() {
    docker stop redteam-katana 2>/dev/null
    docker rm -f redteam-katana 2>/dev/null
    echo "[katana] Stopped and removed"
}

# Stop all engagement containers
stop_all_containers() {
    stop_proxy
    stop_katana
    docker ps -q --filter "ancestor=$REDTEAM_IMAGE" | xargs docker stop 2>/dev/null || true
    echo "[containers] All engagement containers stopped"
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
