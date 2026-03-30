#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/orchestrator.pid"
PORT="${PORT:-18000}"

resolve_lsof() {
  if command -v lsof >/dev/null 2>&1; then
    command -v lsof
    return 0
  fi
  if [[ -x /usr/sbin/lsof ]]; then
    printf '%s\n' /usr/sbin/lsof
    return 0
  fi
  return 1
}

find_listening_pid() {
  local lsof_bin
  lsof_bin="$(resolve_lsof || true)"
  [[ -n "$lsof_bin" ]] || return 0
  "$lsof_bin" -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
}

usage() {
  cat <<EOF
Usage: ./orchestrator/stop.sh

Stops the Redteam Orchestrator GUI service.

Options:
  -h, --help     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  kill "$pid" 2>/dev/null || true
  for _ in {1..10}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
  sleep 1
  ! kill -0 "$pid" 2>/dev/null
}

STOPPED_PID=""

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if stop_pid "${PID:-}"; then
    STOPPED_PID="$PID"
  fi
  rm -f "$PID_FILE"
fi

LISTEN_PID="$(find_listening_pid || true)"
if [[ -n "${LISTEN_PID:-}" ]]; then
  LISTEN_CMD="$(ps -p "$LISTEN_PID" -o command= 2>/dev/null || true)"
  if [[ "$LISTEN_CMD" == *"uvicorn app.main:app"* ]]; then
    stop_pid "$LISTEN_PID" >/dev/null 2>&1 || true
    STOPPED_PID="${STOPPED_PID:-$LISTEN_PID}"
  fi
fi

if [[ -n "$STOPPED_PID" ]]; then
  echo "Orchestrator stopped."
  echo "PID: $STOPPED_PID"
  exit 0
fi

echo "Orchestrator is not running."
