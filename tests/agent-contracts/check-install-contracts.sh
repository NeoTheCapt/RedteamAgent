#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
INSTALL_SH="$ROOT/install.sh"

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! rg -q --fixed-strings -- "$pattern" "$file"; then
    echo "[FAIL] Missing pattern in $file: $pattern" >&2
    exit 1
  fi
}

assert_contains "$INSTALL_SH" 'REDTEAM_SKIP_PREREQ_CHECKS'
assert_contains "$INSTALL_SH" 'REDTEAM_SKIP_DOCKER_IMAGE_CHECKS'
assert_contains "$INSTALL_SH" 'Skipping prerequisite checks'
assert_contains "$INSTALL_SH" 'Skipping Docker image build/verification'

echo "[OK] install contract checks passed"
