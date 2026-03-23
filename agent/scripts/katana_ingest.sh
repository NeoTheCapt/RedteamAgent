#!/usr/bin/env bash
# katana_ingest.sh — Start Katana crawler container and ingest JSONL output into SQLite queue.
# Usage: ./scripts/katana_ingest.sh <engagement_dir> [additional_katana_flags]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/classify.sh"
source "$SCRIPT_DIR/lib/db.sh"
source "$SCRIPT_DIR/lib/container.sh"
source "$SCRIPT_DIR/lib/noise.sh"

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

# --- Start Katana container ---
start_katana "$TARGET" "${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}"

# --- Monitor output and ingest ---
echo "[katana_ingest] Monitoring $KATANA_OUTPUT for new crawl results..."
count=0

# tail -f the output file, process each new JSONL line
# Use process substitution to avoid subshell (so count increments correctly)
while IFS= read -r line; do
    # Skip empty lines
    [[ -z "$line" ]] && continue

    # Extract URL — try request.endpoint first, then request.url, then bare string
    url=$(echo "$line" | jq -r '.request.endpoint // .request.url // .url // empty' 2>/dev/null)
    if [[ -z "$url" ]]; then
        # Maybe line is a plain URL
        if echo "$line" | grep -qE '^https?://'; then
            url="$line"
        else
            continue
        fi
    fi

    # Extract method (default GET)
    method=$(echo "$line" | jq -r '.request.method // "GET"' 2>/dev/null || echo "GET")
    method=$(printf '%s' "$method" | tr '[:lower:]' '[:upper:]')

    # Extract content type from response if available
    content_type=$(echo "$line" | jq -r '.response.headers["content-type"] // .response.headers["Content-Type"] // ""' 2>/dev/null || true)

    # Extract response status
    resp_status=$(echo "$line" | jq -r '.response.status_code // 0' 2>/dev/null || echo "0")

    # Run through parameter extraction pipeline
    url_path=$(extract_url_path "$url")
    if is_katana_noise_path "$url_path"; then
        continue
    fi
    query_params=$(extract_query_params "$url")
    path_params=$(extract_path_params "$url_path")
    body_params="{}"
    cookie_params="{}"

    # Classify type
    case_type=$(classify_type "$method" "$url_path" "$content_type" "")

    # Generate dedup signature
    params_sig=$(generate_params_sig "$query_params" "$body_params")

    # Insert into DB
    db_insert_case "$DB_PATH" \
        "$method" "$url" "$url_path" \
        "$query_params" "$body_params" "$path_params" "$cookie_params" \
        "" "" "$content_type" "0" \
        "$resp_status" "" "0" "" \
        "$case_type" "katana" "$params_sig"

    count=$((count + 1))
    if (( count % 50 == 0 )); then
        echo "[katana_ingest] Ingested $count cases so far..."
    fi
done < <(tail -f "$KATANA_OUTPUT" 2>/dev/null)

echo "[katana_ingest] Ingested $count total cases from $TARGET"
