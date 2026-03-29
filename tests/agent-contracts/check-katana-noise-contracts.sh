#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NOISE_LIB="$ROOT_DIR/agent/scripts/lib/noise.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -f "$NOISE_LIB" ]] || fail "missing noise library: $NOISE_LIB"

# shellcheck source=/dev/null
source "$NOISE_LIB"

expect_noise() {
  local path="$1"
  if ! is_katana_noise_path "$path"; then
    fail "expected noise path: $path"
  fi
}

expect_keep() {
  local path="$1"
  if is_katana_noise_path "$path"; then
    fail "expected real path to survive: $path"
  fi
}

expect_noise '/%7B%7Bhref%7D%7D'
expect_noise "/'+L(i[8])+'"
expect_noise '/application/vnd.ms-word.do'
expect_noise '/Edge/'
expect_noise '/Trident/'
expect_noise '/-'
expect_noise '/rest/admin/%5C%22/'
expect_noise '/api/%5C%22/ftp/legal.md%5C%22'
expect_noise '/%5C/index.html'
expect_noise '/*?*&src=*'
expect_noise '/*/kyc-verify$'
expect_noise '/cdn/assets/okfe/okt/polyfill-automatic/Bun/'
expect_noise '/cdn/assets/okfe/util/monitor/2.6.149/scripts/lib/'
expect_noise '/assets/public/images/'
expect_noise '/assets/public/images/chunk-24EZLZ4I.js'
expect_noise '/assets/public/images/assets/public/main.js'
expect_noise '/assets/i18n/assets/public/polyfills.js'

expect_keep '/rest/user/login'
expect_keep '/rest/products/42/reviews'
expect_keep '/address/create'
expect_keep '/track-result/new'

echo "katana noise contracts: ok"
