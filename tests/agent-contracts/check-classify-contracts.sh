#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CLASSIFY_LIB="$ROOT_DIR/agent/scripts/lib/classify.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -f "$CLASSIFY_LIB" ]] || fail "missing classify library: $CLASSIFY_LIB"

# shellcheck source=/dev/null
source "$CLASSIFY_LIB"

expect_type() {
  local expected="$1"
  local method="$2"
  local path="$3"
  local content_type="${4:-}"
  local body="${5:-}"

  local actual
  actual="$(classify_type "$method" "$path" "$content_type" "$body")"
  [[ "$actual" == "$expected" ]] || fail "expected $expected for $method $path, got $actual"
}

expect_type api "GET" "/rest/user/login"
expect_type api "GET" "/api"
expect_type api "GET" "/rest"
expect_type api-spec "GET" "/api-docs"
expect_type api-spec "GET" "/openapi.json"
expect_type websocket "GET" "/socket.io/"
expect_type data "GET" "/robots.txt"
expect_type data "GET" "/.well-known/security.txt"

echo "classify contracts: ok"
