#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/orchestrator.pid"
LOG_FILE="$RUN_DIR/orchestrator.log"
BACKEND_VENV="$BACKEND_DIR/.venv"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18000}"
FOREGROUND=0
REBUILD_IMAGE=0

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
Usage: ./orchestrator/run.sh [--foreground] [--rebuild]

Starts the Redteam Orchestrator GUI service.

Options:
  --foreground   Run uvicorn in the foreground instead of daemonizing.
  --rebuild      Rebuild redteam-allinone:latest and :dev before starting.
  -h, --help     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --rebuild)
      REBUILD_IMAGE=1
      shift
      ;;
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

mkdir -p "$RUN_DIR"

CURRENT_NOFILE="$(ulimit -n 2>/dev/null || printf '0')"
DESIRED_NOFILE="${ORCH_NOFILE_LIMIT:-4096}"
if [[ "$CURRENT_NOFILE" =~ ^[0-9]+$ ]] && [[ "$DESIRED_NOFILE" =~ ^[0-9]+$ ]] && (( CURRENT_NOFILE < DESIRED_NOFILE )); then
  ulimit -n "$DESIRED_NOFILE" 2>/dev/null || true
fi

if [[ ! -d "$BACKEND_VENV" ]]; then
  python3 -m venv "$BACKEND_VENV"
fi

"$BACKEND_VENV/bin/python" -m pip install --quiet --upgrade pip
"$BACKEND_VENV/bin/python" -m pip install --quiet -e "$BACKEND_DIR"

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  (cd "$FRONTEND_DIR" && npm install)
fi

(cd "$FRONTEND_DIR" && npm run build >/dev/null)

if [[ "$REBUILD_IMAGE" -eq 1 ]]; then
  echo "Rebuilding redteam-allinone:latest and redteam-allinone:dev ..."
  (
    cd "$ROOT_DIR/.."
    docker build -t redteam-allinone:latest -t redteam-allinone:dev -f agent/docker/redteam-allinone/Dockerfile .
  )
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

LISTEN_PID="$(find_listening_pid || true)"
if [[ -n "${LISTEN_PID:-}" ]]; then
  LISTEN_CMD="$(ps -p "$LISTEN_PID" -o command= 2>/dev/null || true)"
  if [[ "$LISTEN_CMD" == *"uvicorn app.main:app"* ]]; then
    echo "$LISTEN_PID" >"$PID_FILE"
    echo "Orchestrator already running."
    echo "URL: http://$HOST:$PORT"
    echo "PID: $LISTEN_PID"
    exit 0
  fi
  echo "Port $PORT is already in use by another process: $LISTEN_CMD" >&2
  exit 1
fi

CMD=(
  "$BACKEND_VENV/bin/python" -m uvicorn
  app.main:app
  --host "$HOST"
  --port "$PORT"
)

if [[ "$FOREGROUND" -eq 1 ]]; then
  echo "Starting orchestrator in foreground: http://$HOST:$PORT"
  cd "$BACKEND_DIR"
  exec "${CMD[@]}"
fi

export ORCH_BACKEND_DIR="$BACKEND_DIR"
export ORCH_LOG_FILE="$LOG_FILE"
export ORCH_PID_FILE="$PID_FILE"
export ORCH_HOST="$HOST"
export ORCH_PORT="$PORT"

"$BACKEND_VENV/bin/python" - <<'PY'
import os
import subprocess
from pathlib import Path

backend_dir = Path(os.environ["ORCH_BACKEND_DIR"])
log_file = Path(os.environ["ORCH_LOG_FILE"])
pid_file = Path(os.environ["ORCH_PID_FILE"])
host = os.environ["ORCH_HOST"]
port = os.environ["ORCH_PORT"]

log_file.parent.mkdir(parents=True, exist_ok=True)
with log_file.open("wb") as log_handle:
    process = subprocess.Popen(
        [
            str(backend_dir / ".venv" / "bin" / "python"),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            port,
        ],
        cwd=str(backend_dir),
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
PY

STARTED=0
for _ in {1..20}; do
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
      STARTED=1
      break
    fi
  else
    break
  fi
  sleep 1
done

if [[ "$STARTED" -ne 1 ]]; then
  echo "Failed to start orchestrator; see $LOG_FILE" >&2
  exit 1
fi

echo "Orchestrator started."
echo "URL: http://$HOST:$PORT"
echo "PID: $(cat "$PID_FILE")"
echo "Log: $LOG_FILE"
