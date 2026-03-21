#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/../../agent" && pwd)"
IMAGE_NAME="opencode-runner"

# Build if image doesn't exist
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "Building $IMAGE_NAME..."
  docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
fi

# Load .env if exists
ENV_ARGS=""
if [ -f "$SCRIPT_DIR/.env" ]; then
  ENV_ARGS="--env-file $SCRIPT_DIR/.env"
fi

# Detect TTY
TTY_FLAG="-it"
[ -t 0 ] || TTY_FLAG="-i"

# Run OpenCode in a fresh container, destroyed on exit
exec docker run --rm $TTY_FLAG \
  -v "$AGENT_DIR:/workspace" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --add-host host.docker.internal:host-gateway \
  -e TERM=xterm-256color \
  $ENV_ARGS \
  "$IMAGE_NAME" "$@"
