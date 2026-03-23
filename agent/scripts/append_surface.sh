#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/surfaces.sh"

ENG_DIR="${1:?usage: append_surface.sh <engagement_dir> <surface_type> <target> <source> <rationale> [evidence_ref] [status]}"
SURFACE_TYPE="${2:?usage: append_surface.sh <engagement_dir> <surface_type> <target> <source> <rationale> [evidence_ref] [status]}"
TARGET="${3:?usage: append_surface.sh <engagement_dir> <surface_type> <target> <source> <rationale> [evidence_ref] [status]}"
SOURCE_NAME="${4:?usage: append_surface.sh <engagement_dir> <surface_type> <target> <source> <rationale> [evidence_ref] [status]}"
RATIONALE="${5:-}"
EVIDENCE_REF="${6:-}"
STATUS="${7:-discovered}"

upsert_surface_record "$ENG_DIR" "$SURFACE_TYPE" "$TARGET" "$SOURCE_NAME" "$RATIONALE" "$EVIDENCE_REF" "$STATUS"
