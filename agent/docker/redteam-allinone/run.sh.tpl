#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="${REDTEAM_ALLINONE_IMAGE:-redteam-allinone:latest}"
WORKSPACE_DIR="${REDTEAM_WORKSPACE_DIR:-$SCRIPT_DIR/workspace}"
OPENCODE_HOME_DIR="${REDTEAM_OPENCODE_HOME_DIR:-$SCRIPT_DIR/opencode-home}"
ENV_FILE="${REDTEAM_ENV_FILE:-$SCRIPT_DIR/.env}"
DOCKERFILE_PATH="${REDTEAM_DOCKERFILE_PATH:-$SCRIPT_DIR/agent/docker/redteam-allinone/Dockerfile}"

RESET=false
REBUILD=false
EPHEMERAL_OPENCODE=false

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
    --ephemeral-opencode|--no-persist-opencode)
      EPHEMERAL_OPENCODE=true
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
if ! $EPHEMERAL_OPENCODE; then
  mkdir -p "$OPENCODE_HOME_DIR"
fi

if $RESET; then
  rm -rf "$WORKSPACE_DIR"
  mkdir -p "$WORKSPACE_DIR"
  if ! $EPHEMERAL_OPENCODE; then
    rm -rf "$OPENCODE_HOME_DIR"
    mkdir -p "$OPENCODE_HOME_DIR"
  fi
fi

if $REBUILD || ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  docker build -t "$IMAGE_NAME" -f "$DOCKERFILE_PATH" "$SCRIPT_DIR"
fi

if [ $# -eq 0 ]; then
  set -- opencode
fi

docker_args=(
  --rm
  -v "$WORKSPACE_DIR:/workspace"
  --env-file "$ENV_FILE"
)

if ! $EPHEMERAL_OPENCODE; then
  docker_args+=(-v "$OPENCODE_HOME_DIR:/root/.local/share/opencode")
fi

if [ -t 0 ] && [ -t 1 ]; then
  docker_args+=(-it)
  docker run "${docker_args[@]}" \
    "$IMAGE_NAME" \
    "$@"
else
  docker run "${docker_args[@]}" \
    "$IMAGE_NAME" \
    "$@"
fi
