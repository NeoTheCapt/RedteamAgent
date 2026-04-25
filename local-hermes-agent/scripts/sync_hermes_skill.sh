#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_SKILL_DIR="$ROOT_DIR/skills/scan-optimizer-loop"
WORKSPACE_SKILLS_DIR="$HOME/.openclaw/workspace/skills"
DST_SKILL_DIR="$WORKSPACE_SKILLS_DIR/scan-optimizer-loop"

mkdir -p "$WORKSPACE_SKILLS_DIR"
rm -rf "$DST_SKILL_DIR"
cp -R "$SRC_SKILL_DIR" "$DST_SKILL_DIR"

echo "Copied workspace skill: $SRC_SKILL_DIR -> $DST_SKILL_DIR"
