#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agent"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"

SPEC_FIXTURE="$TMP_DIR/spec.json"
cat > "$SPEC_FIXTURE" <<'EOF'
{
  "openapi": "3.0.0",
  "servers": [{"url": "https://app.example.com"}],
  "paths": {
    "/api/users": {
      "get": {}
    }
  }
}
EOF

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >> "${FAKE_CURL_LOG:?}"
out=""
while (($#)); do
  case "$1" in
    -o)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
cp "${FAKE_SPEC_FIXTURE:?}" "$out"
EOF
chmod +x "$FAKE_BIN/curl"

cat > "$FAKE_BIN/jq" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/jq "$@"
EOF
chmod +x "$FAKE_BIN/jq"

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "[FAIL] $msg" >&2
    echo "Missing: $needle" >&2
    exit 1
  fi
}

assert_empty() {
  local file="$1" msg="$2"
  if [[ -s "$file" ]]; then
    echo "[FAIL] $msg" >&2
    cat "$file" >&2
    exit 1
  fi
}

export PATH="$FAKE_BIN:$PATH"
export FAKE_CURL_LOG="$TMP_DIR/curl.log"
export FAKE_SPEC_FIXTURE="$SPEC_FIXTURE"

ENG_DIR="$TMP_DIR/engagement"
mkdir -p "$ENG_DIR/tools" "$ENG_DIR/scans"
sqlite3 "$ENG_DIR/cases.db" < "$AGENT_DIR/scripts/schema.sql" >/dev/null
cat > "$ENG_DIR/scope.json" <<'EOF'
{"hostname":"app.example.com","scope":["app.example.com"]}
EOF
printf 'Mozilla/5.0 Test\n' > "$ENG_DIR/user-agent.txt"

cat > "$ENG_DIR/tools/rtcurl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >> "${FAKE_RTCURL_LOG:?}"
out=""
while (($#)); do
  case "$1" in
    -o)
      out="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
cp "${FAKE_SPEC_FIXTURE:?}" "$out"
EOF
chmod +x "$ENG_DIR/tools/rtcurl"

export FAKE_RTCURL_LOG="$TMP_DIR/rtcurl.log"
: > "$FAKE_CURL_LOG"
: > "$FAKE_RTCURL_LOG"

bash "$AGENT_DIR/scripts/spec_ingest.sh" "$ENG_DIR/cases.db" "https://app.example.com/openapi.json" >/dev/null

RTCURL_ARGS="$(tr '\n' ' ' < "$FAKE_RTCURL_LOG")"
assert_contains "$RTCURL_ARGS" "https://app.example.com/openapi.json" "spec_ingest should route remote spec download through engagement rtcurl when available"
assert_empty "$FAKE_CURL_LOG" "raw curl should not be used when engagement rtcurl exists"

rm -f "$ENG_DIR/tools/rtcurl"
: > "$FAKE_CURL_LOG"

bash "$AGENT_DIR/scripts/spec_ingest.sh" "$ENG_DIR/cases.db" "https://app.example.com/openapi.json" >/dev/null

CURL_ARGS="$(tr '\n' ' ' < "$FAKE_CURL_LOG")"
assert_contains "$CURL_ARGS" "https://app.example.com/openapi.json" "spec_ingest should fall back to curl when engagement rtcurl is absent"

echo "[OK] spec_ingest download contracts hold"
