#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/intel.sh"

ENG_DIR="${1:?usage: store_intel_secret.sh <engagement_dir> <ref> <type> <value> <source> [notes]}"
REF="${2:?usage: store_intel_secret.sh <engagement_dir> <ref> <type> <value> <source> [notes]}"
TYPE="${3:?usage: store_intel_secret.sh <engagement_dir> <ref> <type> <value> <source> [notes]}"
VALUE="${4:-}"
SOURCE_NAME="${5:-}"
NOTES="${6:-}"

upsert_intel_secret "$ENG_DIR" "$REF" "$TYPE" "$VALUE" "$SOURCE_NAME" "$NOTES"
PREVIEW="$(truncate_secret_preview "$VALUE")"
printf '| %s | %s | %s | %s | %s |\n' "$TYPE" "$PREVIEW" "$REF" "$SOURCE_NAME" "$NOTES"
