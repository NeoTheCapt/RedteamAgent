#!/usr/bin/env bash
# spec_ingest.sh — Parse OpenAPI 3.x / Swagger 2.0 spec and generate test cases.
# Usage: ./scripts/spec_ingest.sh <db_path> <spec_file_or_url>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/classify.sh"
source "$SCRIPT_DIR/lib/db.sh"

download_spec() {
    local spec_url="$1"
    local output_file="$2"
    local db_dir rtcurl_path

    db_dir="$(dirname "$DB_PATH")"
    rtcurl_path="$db_dir/tools/rtcurl"

    if [[ -x "$rtcurl_path" ]]; then
        RTCURL_AUTH_FILE="$db_dir/auth.json" \
        RTCURL_SCOPE_FILE="$db_dir/scope.json" \
        RTCURL_USER_AGENT_FILE="$db_dir/user-agent.txt" \
        "$rtcurl_path" -sS "$spec_url" -o "$output_file"
        return
    fi

    curl -sS "$spec_url" -o "$output_file"
}

# --- Validate arguments ---
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <db_path> <spec_file_or_url>" >&2
    exit 1
fi

DB_PATH="$1"
SPEC_INPUT="$2"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: database not found: $DB_PATH" >&2
    exit 1
fi

db_init "$DB_PATH"

# --- Fetch spec if URL ---
SPEC_FILE="$SPEC_INPUT"
if [[ "$SPEC_INPUT" == http* ]]; then
    # Download to engagement scans dir, not /tmp
    DB_DIR=$(dirname "$DB_PATH")
    mkdir -p "$DB_DIR/scans"
    SPEC_FILE="$DB_DIR/scans/spec_download.json"
    download_spec "$SPEC_INPUT" "$SPEC_FILE"
fi

if [[ ! -f "$SPEC_FILE" ]]; then
    echo "ERROR: spec file not found: $SPEC_FILE" >&2
    exit 1
fi

# --- Detect spec version ---
OPENAPI_VER=$(jq -r '.openapi // empty' "$SPEC_FILE" 2>/dev/null || true)
SWAGGER_VER=$(jq -r '.swagger // empty' "$SPEC_FILE" 2>/dev/null || true)

if [[ -n "$OPENAPI_VER" ]]; then
    SPEC_VERSION="3"
elif [[ -n "$SWAGGER_VER" ]]; then
    SPEC_VERSION="2"
else
    echo "ERROR: cannot detect spec version (no .openapi or .swagger field)" >&2
    exit 1
fi

# --- Extract base URL ---
if [[ "$SPEC_VERSION" == "3" ]]; then
    BASE_URL=$(jq -r '(.servers[0].url // "")' "$SPEC_FILE" 2>/dev/null || true)
else
    # Swagger 2.0: build from host + basePath + schemes
    HOST=$(jq -r '.host // ""' "$SPEC_FILE" 2>/dev/null || true)
    BASE_PATH=$(jq -r '.basePath // ""' "$SPEC_FILE" 2>/dev/null || true)
    SCHEME=$(jq -r '(.schemes[0] // "https")' "$SPEC_FILE" 2>/dev/null || true)
    if [[ -n "$HOST" ]]; then
        BASE_URL="${SCHEME}://${HOST}${BASE_PATH}"
    else
        BASE_URL=""
    fi
fi

# Remove trailing slash from base URL
BASE_URL="${BASE_URL%/}"

count=0

# --- Extract endpoints ---
# Get all path+method combinations as JSON lines
ENDPOINTS=$(jq -r '
  .paths | to_entries[] | .key as $path | .value | to_entries[] |
  select(.key | test("^(get|post|put|delete|patch)$")) |
  "\(.key|ascii_upcase) \($path)"
' "$SPEC_FILE" 2>/dev/null)

while IFS= read -r endpoint; do
    [[ -z "$endpoint" ]] && continue

    method="${endpoint%% *}"
    path="${endpoint#* }"
    method_lower=$(printf '%s' "$method" | tr '[:upper:]' '[:lower:]')

    full_url="${BASE_URL}${path}"

    # Extract query parameters with examples
    query_params=$(jq -r --arg path "$path" --arg method "${method_lower}" '
      (.paths[$path][$method].parameters // [])
      | [.[] | select(.in == "query")]
      | if length == 0 then "{}"
        else reduce .[] as $p ({}; . + {($p.name): (($p.example // $p.default // "") | tostring)})
        end
    ' "$SPEC_FILE" 2>/dev/null || echo "{}")

    # Extract path parameters with examples
    path_params=$(jq -r --arg path "$path" --arg method "${method_lower}" '
      (.paths[$path][$method].parameters // [])
      | [.[] | select(.in == "path")]
      | if length == 0 then "{}"
        else reduce .[] as $p ({}; . + {($p.name): (($p.example // $p.default // "") | tostring)})
        end
    ' "$SPEC_FILE" 2>/dev/null || echo "{}")

    # Extract body parameters (OpenAPI 3.x)
    body_params="{}"
    if [[ "$SPEC_VERSION" == "3" ]]; then
        body_params=$(jq -r --arg path "$path" --arg method "${method_lower}" '
          (.paths[$path][$method].requestBody.content."application/json".schema.properties // {})
          | if . == {} then "{}"
            else to_entries | reduce .[] as $p ({}; . + {($p.key): (($p.value.example // "") | tostring)})
            end
        ' "$SPEC_FILE" 2>/dev/null || echo "{}")
    else
        # Swagger 2.0: look for body parameter
        body_params=$(jq -r --arg path "$path" --arg method "${method_lower}" '
          (.paths[$path][$method].parameters // [])
          | [.[] | select(.in == "body")]
          | if length == 0 then "{}"
            else .[0].schema.properties // {} |
              if . == {} then "{}"
              else to_entries | reduce .[] as $p ({}; . + {($p.key): (($p.value.example // "") | tostring)})
              end
            end
        ' "$SPEC_FILE" 2>/dev/null || echo "{}")
    fi

    # Build URL with query parameters if any
    url_with_query="$full_url"
    has_query=$(echo "$query_params" | jq 'length > 0' 2>/dev/null || echo "false")
    if [[ "$has_query" == "true" ]]; then
        qs=$(echo "$query_params" | jq -r 'to_entries | map("\(.key)=\(.value)") | join("&")' 2>/dev/null)
        if [[ -n "$qs" ]]; then
            url_with_query="${full_url}?${qs}"
        fi
    fi

    # Extract url_path
    url_path=$(extract_url_path "$url_with_query")

    # Classify type
    case_type=$(classify_type "$method" "$url_path" "" "")

    # Generate dedup signature
    params_sig=$(generate_params_sig "$query_params" "$body_params")

    # Insert into DB
    db_insert_case "$DB_PATH" \
        "$method" "$url_with_query" "$url_path" \
        "$query_params" "$body_params" "$path_params" "{}" \
        "" "" "" "0" \
        "0" "" "0" "" \
        "$case_type" "api-spec" "$params_sig"

    count=$((count + 1))
done <<< "$ENDPOINTS"

# Downloaded spec file is kept in scans/ for reference (not cleaned up)

echo "[spec_ingest] Ingested $count cases from spec (version $SPEC_VERSION)"
