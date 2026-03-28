#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$ROOT_DIR/.." && pwd)"
STATE_DIR="$ROOT_DIR/state"
PROMPTS_DIR="$ROOT_DIR/prompts"
LOGS_DIR="${CYCLE_LOG_DIR:-$ROOT_DIR/logs}"
REFRESH_ORCHESTRATOR="${REFRESH_ORCHESTRATOR:-1}"

mkdir -p "$STATE_DIR" "$LOGS_DIR"

timestamp() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

if [[ "$REFRESH_ORCHESTRATOR" == "1" ]]; then
    echo "[$(timestamp)] restarting local orchestrator to refresh live run state before snapshot..."
    (
        cd "$REPO_DIR"
        ./orchestrator/stop.sh >/dev/null 2>&1 || true
        ./orchestrator/run.sh
    ) | tee "$LOGS_DIR/orchestrator-refresh.log"
fi

echo "[$(timestamp)] building latest run context before taking action..."
"$ROOT_DIR/scripts/build_context.sh" | tee "$LOGS_DIR/build-context.log"

cp "$PROMPTS_DIR/scan-optimizer-loop.txt" "$STATE_DIR/openclaw-prompt.txt"

echo "[$(timestamp)] prepared OpenClaw cycle inputs:"
echo "- context: $STATE_DIR/latest-context.md"
echo "- prompt:  $STATE_DIR/openclaw-prompt.txt"
