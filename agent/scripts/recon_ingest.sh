#!/usr/bin/env bash
# recon_ingest.sh — Read endpoint lists from stdin and insert into the case queue.
# Usage: echo "endpoints" | ./scripts/recon_ingest.sh <db_path> <source_name>
#
# Input formats (auto-detected per line):
#   Simple URL:    GET https://example.com/api/users?id=1
#   Plain URL:     https://example.com/app.js   (defaults to GET)
#   JSON line:     {"method":"GET","url":"https://example.com/api/users","type":"api"}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/classify.sh"
source "$SCRIPT_DIR/lib/db.sh"

# --- Validate arguments ---
if [[ $# -lt 2 ]]; then
    echo "Usage: echo 'endpoints' | $0 <db_path> <source_name>" >&2
    exit 1
fi

DB_PATH="$1"
SOURCE="$2"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: database not found: $DB_PATH" >&2
    exit 1
fi

db_init "$DB_PATH"

count=0

while IFS= read -r line; do
    # Skip empty lines and comments
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^# ]] && continue

    method=""
    url=""
    override_type=""

    if [[ "$line" == "{"* ]]; then
        # JSON format
        method=$(echo "$line" | jq -r '.method // "GET"' 2>/dev/null)
        url=$(echo "$line" | jq -r '.url // empty' 2>/dev/null)
        override_type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)
        if [[ -z "$url" ]]; then
            continue
        fi
    elif [[ "$line" =~ ^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE)[[:space:]] ]]; then
        # Method + URL format: "GET https://host/path [extra data ignored]"
        method="${line%% *}"
        url="${line#* }"
    else
        # Plain URL (default to GET)
        method="GET"
        url="$line"
    fi

    # Strip URL to first token only — ignore any trailing data (status codes, notes, tabs, etc.)
    url=$(printf '%s' "$url" | awk '{print $1}')
    method=$(printf '%s' "$method" | tr '[:lower:]' '[:upper:]')

    # Skip URLs containing ffuf/fuzzing placeholders
    if [[ "$url" == *"FUZZ"* || "$url" == *"PARAM"* || "$url" == *"{{"* ]]; then
        continue
    fi

    # Skip if URL is empty
    [[ -z "$url" ]] && continue

    # If URL doesn't start with http, it might be a bare hostname — prefix with https://
    if [[ ! "$url" =~ ^https?:// ]]; then
        # Check if it looks like a hostname (contains dots, no slashes at start)
        if echo "$url" | grep -qE '^[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}'; then
            url="https://$url"
        fi
    fi

    # Run through parameter extraction pipeline
    url_path=$(extract_url_path "$url")
    query_params=$(extract_query_params "$url")
    path_params=$(extract_path_params "$url_path")
    body_params="{}"

    # Classify type (use override if provided)
    if [[ -n "$override_type" ]]; then
        case_type="$override_type"
    else
        case_type=$(classify_type "$method" "$url_path" "" "")
    fi

    # Generate dedup signature
    params_sig=$(generate_params_sig "$query_params" "$body_params")

    # Insert into DB
    db_insert_case "$DB_PATH" \
        "$method" "$url" "$url_path" \
        "$query_params" "$body_params" "$path_params" "{}" \
        "" "" "" "0" \
        "0" "" "0" "" \
        "$case_type" "$SOURCE" "$params_sig"

    count=$((count + 1))
done

echo "[recon_ingest] Inserted $count cases from source '$SOURCE'"
