#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="${REDTEAM_ALLINONE_IMAGE:-redteam-allinone:latest}"
WORKSPACE_DIR="${REDTEAM_WORKSPACE_DIR:-$SCRIPT_DIR/workspace}"
ENV_FILE="${REDTEAM_ENV_FILE:-$SCRIPT_DIR/.env}"
DOCKERFILE_PATH="${REDTEAM_DOCKERFILE_PATH:-$SCRIPT_DIR/docker/redteam-allinone/Dockerfile}"

RESET=false
REBUILD=false

while [ $# -gt 0 ]; do
  case "$1" in
    --reset)
      RESET=true
      shift
      ;;
    --rebuild|--build)
      REBUILD=true
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [ ! -f "$ENV_FILE" ] && [ -f "$SCRIPT_DIR/.env.example" ]; then
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
  echo "[WARN] Created $ENV_FILE from template. Update API keys before use."
fi

mkdir -p "$WORKSPACE_DIR"

if $RESET; then
  rm -rf "$WORKSPACE_DIR"
  mkdir -p "$WORKSPACE_DIR"
fi

if $REBUILD || ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  docker build -t "$IMAGE_NAME" -f "$DOCKERFILE_PATH" "$SCRIPT_DIR"
fi

if [ $# -eq 0 ]; then
  set -- opencode
fi

if [ -t 0 ] && [ -t 1 ]; then
  docker run --rm -it \
    -v "$WORKSPACE_DIR:/workspace" \
    --env-file "$ENV_FILE" \
    "$IMAGE_NAME" \
    "$@"
else
  docker run --rm \
    -v "$WORKSPACE_DIR:/workspace" \
    --env-file "$ENV_FILE" \
    "$IMAGE_NAME" \
    "$@"
fi
