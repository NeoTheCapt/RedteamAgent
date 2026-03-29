#!/usr/bin/env bash
# katana_ingest.sh — Start Katana crawler container and ingest JSONL output into SQLite queue.
# Usage: ./scripts/katana_ingest.sh <engagement_dir> [additional_katana_flags]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/classify.sh"
source "$SCRIPT_DIR/lib/db.sh"
source "$SCRIPT_DIR/lib/container.sh"
source "$SCRIPT_DIR/lib/katana.sh"
source "$SCRIPT_DIR/lib/noise.sh"
source "$SCRIPT_DIR/lib/loopback_scope.sh"

# --- Validate arguments ---
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <engagement_dir> [additional_katana_flags]" >&2
    exit 1
fi

ENGAGEMENT_DIR_RAW="$1"
shift
EXTRA_FLAGS=("$@")

if [[ ! -d "$ENGAGEMENT_DIR_RAW" ]]; then
    echo "ERROR: engagement directory not found: $ENGAGEMENT_DIR_RAW" >&2
    exit 1
fi

# Resolve to absolute path (Docker -v requires absolute paths)
if [[ "$ENGAGEMENT_DIR_RAW" = /* ]]; then
    export ENGAGEMENT_DIR="$ENGAGEMENT_DIR_RAW"
else
    export ENGAGEMENT_DIR="$(cd "$ENGAGEMENT_DIR_RAW" && pwd)"
fi

# --- Read target from scope.json ---
SCOPE_FILE="$ENGAGEMENT_DIR/scope.json"
if [[ ! -f "$SCOPE_FILE" ]]; then
    echo "ERROR: scope.json not found in $ENGAGEMENT_DIR" >&2
    exit 1
fi

TARGET=$(jq -r '.target' "$SCOPE_FILE")
if [[ -z "$TARGET" || "$TARGET" == "null" ]]; then
    echo "ERROR: no target found in scope.json" >&2
    exit 1
fi

# --- Ensure DB exists ---
DB_PATH="$ENGAGEMENT_DIR/cases.db"
if [[ ! -f "$DB_PATH" ]]; then
    sqlite3 "$DB_PATH" < "$SCRIPT_DIR/schema.sql"
fi
db_init "$DB_PATH"

# --- Ensure scans directory exists ---
mkdir -p "$ENGAGEMENT_DIR/scans"

# --- Output file (Katana writes here, we tail it) ---
KATANA_OUTPUT="$ENGAGEMENT_DIR/scans/katana_output.jsonl"
touch "$KATANA_OUTPUT"

count=0

ingest_request() {
    local method="${1:-GET}"
    local url="${2:-}"
    local content_type="${3:-}"
    local resp_status="${4:-0}"
    local source_name="${5:-katana}"
    local body_params="{}"
    local cookie_params="{}"
    local query_params path_params url_path case_type params_sig

    [[ -n "$url" ]] || return 0
    method=$(printf '%s' "$method" | tr '[:lower:]' '[:upper:]')

    local normalized_url
    normalized_url="$(normalize_target_for_scope "$ENGAGEMENT_DIR" "$url")" || {
        if [[ $? -eq 10 ]]; then
            return 0
        fi
        return 0
    }
    url="$normalized_url"

    url_path=$(extract_url_path "$url")
    [[ -n "$url_path" ]] || return 0
    if is_katana_noise_path "$url_path"; then
        return 0
    fi

    query_params=$(extract_query_params "$url")
    path_params=$(extract_path_params "$url_path")
    case_type=$(classify_type "$method" "$url_path" "$content_type" "")
    params_sig=$(generate_params_sig "$query_params" "$body_params")

    db_insert_case "$DB_PATH" \
        "$method" "$url" "$url_path" \
        "$query_params" "$body_params" "$path_params" "$cookie_params" \
        "" "" "$content_type" "0" \
        "$resp_status" "" "0" "" \
        "$case_type" "$source_name" "$params_sig"

    count=$((count + 1))
    if (( count % 50 == 0 )); then
        echo "[katana_ingest] Ingested $count cases so far..."
    fi
}

ingest_katana_line() {
    local line="${1:-}"
    local url method content_type resp_status request_json

    [[ -n "$line" ]] || return 0

    if ! katana_line_should_ingest "$line"; then
        return 0
    fi

    if printf '%s' "$line" | grep -qE '^https?://'; then
        ingest_request "GET" "$line" "" "0" "katana"
        return 0
    fi

    while IFS= read -r request_json; do
        [[ -n "$request_json" ]] || continue
        if ! katana_request_should_ingest "$request_json"; then
            continue
        fi
        url=$(printf '%s' "$request_json" | jq -r '.url // empty' 2>/dev/null || true)
        [[ -n "$url" ]] || continue
        method=$(printf '%s' "$request_json" | jq -r '.method // "GET"' 2>/dev/null || echo "GET")
        content_type=$(printf '%s' "$request_json" | jq -r '.content_type // ""' 2>/dev/null || true)
        resp_status=$(printf '%s' "$request_json" | jq -r '.response_status // 0' 2>/dev/null || echo "0")
        ingest_request "$method" "$url" "$content_type" "$resp_status" "$(printf '%s' "$request_json" | jq -r '.source // "katana"' 2>/dev/null || echo "katana")"
    done < <(
        printf '%s' "$line" | jq -c '
            [
              {
                method: (.request.method // "GET"),
                url: (.request.endpoint // .request.url // .url // empty),
                content_type: (.response.headers["content-type"] // .response.headers["Content-Type"] // ""),
                response_status: (.response.status_code // 0),
                source: "katana",
                source_ref: (.request.source // ""),
                tag: (.request.tag // ""),
                attribute: (.request.attribute // ""),
                error: (.error // "")
              },
              (.response.xhr_requests[]? | {
                method: (.method // "GET"),
                url: (.endpoint // .url // empty),
                content_type: (.headers["content-type"] // .headers["Content-Type"] // ""),
                response_status: 0,
                source: "katana-xhr",
                source_ref: (.source // .request.source // ""),
                tag: (.tag // ""),
                attribute: (.attribute // ""),
                error: (.error // "")
              })
            ]
            | .[]
            | select((.url // "") != "")
        ' 2>/dev/null || true
    )
}

ingest_output_snapshot() {
    local output_file="$1"
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        ingest_katana_line "$line"
    done < "$output_file"
}

# --- Start Katana container unless explicitly skipped for re-ingest/verification ---
if [[ "${KATANA_INGEST_SKIP_START:-0}" != "1" ]]; then
    start_katana "$TARGET" "${EXTRA_FLAGS[@]}"
fi

# --- Monitor output and ingest ---
echo "[katana_ingest] Monitoring $KATANA_OUTPUT for crawl results..."

if [[ "${KATANA_INGEST_ONESHOT:-0}" == "1" ]]; then
    ingest_output_snapshot "$KATANA_OUTPUT"
else
    # Katana may leave the newest JSON row unterminated for long stretches. Re-scan the file
    # whenever its size changes so already-written crawl results are ingested without waiting
    # for a trailing newline.
    last_size=""
    poll_seconds="${KATANA_INGEST_POLL_SECONDS:-2}"
    while true; do
        current_size="$(wc -c < "$KATANA_OUTPUT" | tr -d '[:space:]')"
        if [[ "$current_size" != "$last_size" ]]; then
            ingest_output_snapshot "$KATANA_OUTPUT"
            last_size="$current_size"
        fi
        sleep "$poll_seconds"
    done
fi

echo "[katana_ingest] Ingested $count total cases from $TARGET"
