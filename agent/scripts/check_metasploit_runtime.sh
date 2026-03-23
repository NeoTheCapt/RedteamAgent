#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "${BASH_SOURCE[0]%/*}/.." && pwd)
ROOT_DIR="$SCRIPT_DIR"
. "$ROOT_DIR/scripts/lib/processes.sh"
COMPOSE_FILE="${METASPLOIT_COMPOSE_FILE:-$ROOT_DIR/docker/docker-compose.yml}"
SERVICE_NAME="${METASPLOIT_SERVICE_NAME:-metasploit}"
ENV_FILE="$ROOT_DIR/.env"
MSF_HOST="${MSF_SERVER:-${METASPLOIT_RUNTIME_HOST:-127.0.0.1}}"
MSF_PORT="${MSF_PORT:-${METASPLOIT_RUNTIME_PORT:-55553}}"
RUNTIME_MODE="${REDTEAM_RUNTIME_MODE:-docker}"
PID_DIR="${METASPLOIT_PID_DIR:-$ROOT_DIR/pids}"
LOCAL_CMD_DEFAULT="msfrpcd -P ${MSF_PASSWORD:-msf} -U ${MSF_USER:-msf} -a ${MSF_HOST} -p ${MSF_PORT} -S"
LOCAL_CMD="${METASPLOIT_LOCAL_CMD:-$LOCAL_CMD_DEFAULT}"

ensure_runtime=false
probe_port=false

while [ $# -gt 0 ]; do
  case "$1" in
    --ensure|--ensure-started)
      ensure_runtime=true
      ;;
    --probe-port)
      probe_port=true
      ;;
    --no-probe-port)
      probe_port=false
      ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--ensure|--ensure-started] [--probe-port]

Checks whether the Metasploit runtime container is available.
--ensure     Attempt to start the service once if it is not running.
--ensure-started  Alias for --ensure.
--probe-port Probe the local RPC port after the container is running.
EOF
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

if [ -f "$ENV_FILE" ] && { [ -z "${MSF_SERVER:-}" ] || [ -z "${MSF_PORT:-}" ]; }; then
  set -a
  . "$ENV_FILE"
  set +a
  MSF_HOST="${MSF_SERVER:-${METASPLOIT_RUNTIME_HOST:-127.0.0.1}}"
  MSF_PORT="${MSF_PORT:-${METASPLOIT_RUNTIME_PORT:-55553}}"
fi

RUNTIME_MODE="${REDTEAM_RUNTIME_MODE:-$RUNTIME_MODE}"
PID_DIR="${METASPLOIT_PID_DIR:-$PID_DIR}"
LOCAL_CMD_DEFAULT="msfrpcd -P ${MSF_PASSWORD:-msf} -U ${MSF_USER:-msf} -a ${MSF_HOST} -p ${MSF_PORT} -S"
LOCAL_CMD="${METASPLOIT_LOCAL_CMD:-$LOCAL_CMD_DEFAULT}"

local_runtime_is_running() {
  pid_is_running "$(pid_file_path "$PID_DIR" "$SERVICE_NAME")"
}

local_start_service_once() {
  echo "[metasploit] Runtime unavailable, starting local $SERVICE_NAME..." >&2
  start_managed_process "$PID_DIR" "$SERVICE_NAME" bash -lc "$LOCAL_CMD" >/dev/null
}

local_probe_ready() {
  if [ "${METASPLOIT_RUNTIME_SKIP_PORT_PROBE:-0}" = "1" ]; then
    return 0
  fi
  probe_rpc_port
}

if [ "$RUNTIME_MODE" = "local" ]; then
  if ! local_runtime_is_running; then
    if [ "$ensure_runtime" = true ]; then
      local_start_service_once
      if ! local_runtime_is_running; then
        echo "ERROR: local Metasploit runtime is still not running after startup attempt" >&2
        exit 1
      fi
    else
      echo "ERROR: local Metasploit runtime is not running. Set REDTEAM_RUNTIME_MODE=local and start msfrpcd." >&2
      exit 1
    fi
  fi
  if [ "$probe_port" = true ]; then
    local_probe_ready
  fi
  echo "[OK] Metasploit runtime is available"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running" >&2
  exit 1
fi

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

service_container_id() {
  compose ps -q "$SERVICE_NAME" 2>/dev/null | head -n1
}

service_is_running() {
  local container_id
  container_id="$(service_container_id)"
  if [ -z "$container_id" ]; then
    return 1
  fi
  [ "$(docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || echo false)" = "true" ]
}

start_service_once() {
  echo "[metasploit] Runtime unavailable, starting $SERVICE_NAME via docker compose..." >&2
  compose up -d "$SERVICE_NAME" >/dev/null
}

probe_rpc_port() {
  local attempt
  for attempt in 1 2 3 4 5; do
    if bash -lc "exec 3<>/dev/tcp/${MSF_HOST}/${MSF_PORT}" >/dev/null 2>&1; then
      exec 3>&- 3<&- 2>/dev/null || true
      return 0
    fi
    sleep 1
  done
  echo "ERROR: Metasploit RPC port ${MSF_PORT} is not reachable on ${MSF_HOST}" >&2
  return 1
}

if ! service_is_running; then
  if [ "$ensure_runtime" = true ]; then
    start_service_once
    if ! service_is_running; then
      echo "ERROR: Metasploit runtime is still not running after startup attempt" >&2
      exit 1
    fi
  else
    echo "ERROR: Metasploit runtime is not running. Start it with: docker compose -f \"$COMPOSE_FILE\" up -d \"$SERVICE_NAME\"" >&2
    exit 1
  fi
fi

if [ "$probe_port" = true ] && [ "${METASPLOIT_RUNTIME_SKIP_PORT_PROBE:-0}" != "1" ]; then
  probe_rpc_port
fi

echo "[OK] Metasploit runtime is available"
