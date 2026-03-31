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
LAST_OFFSET=0
INGEST_REMAINDER=""
KATANA_INGEST_STARTED_KATANA=0
KATANA_FALLBACK_ACTIVATED=0
KATANA_FALLBACK_STALL_SECONDS="${KATANA_FALLBACK_STALL_SECONDS:-90}"
KATANA_FALLBACK_RECOVERABLE_THRESHOLD="${KATANA_FALLBACK_RECOVERABLE_THRESHOLD:-8}"
KATANA_LAST_SUCCESS_TS=0
KATANA_LAST_OUTPUT_CHANGE_TS=0
KATANA_RECOVERABLE_ERROR_LINES=0
KATANA_SUCCESS_LINES=0
KATANA_INGEST_EXIT_GRACE_SECONDS="${KATANA_INGEST_EXIT_GRACE_SECONDS:-10}"

cleanup_katana_ingest() {
    if [[ "$KATANA_INGEST_STARTED_KATANA" == "1" ]]; then
        stop_katana >/dev/null 2>&1 || true
    fi
    rm -f "$(pid_file_path "$ENGAGEMENT_DIR/pids" "katana_ingest")"
}
trap cleanup_katana_ingest EXIT

katana_runtime_active() {
    [[ "$KATANA_INGEST_STARTED_KATANA" == "1" ]] || return 1

    if [[ "$(runtime_mode)" == "local" ]]; then
        pid_is_running "$(_pid_file "katana")"
        return $?
    fi

    local container_name
    container_name="$(_katana_container_name)" || return 1
    docker ps --format '{{.Names}}' | grep -q "^${container_name}$"
}

maybe_finish_ingest_loop() {
    local now elapsed_since_output

    [[ "$KATANA_INGEST_STARTED_KATANA" == "1" ]] || return 1
    katana_runtime_active && return 1

    now="$(date +%s)"
    elapsed_since_output=$((now - KATANA_LAST_OUTPUT_CHANGE_TS))
    if (( elapsed_since_output < KATANA_INGEST_EXIT_GRACE_SECONDS )); then
        return 1
    fi

    if [[ -n "$INGEST_REMAINDER" ]]; then
        ingest_katana_line "$INGEST_REMAINDER"
        INGEST_REMAINDER=""
    fi

    return 0
}

maybe_log_progress() {
    if (( count > 0 && count % 50 == 0 )); then
        echo "[katana_ingest] Ingested $count cases so far..."
    fi
}

katana_line_counts_as_success() {
    local line="${1:-}"
    local url method content_type url_path case_type xhr_count

    [[ -n "$line" ]] || return 1

    if printf '%s' "$line" | jq -e '.error? // empty' >/dev/null 2>&1; then
        return 1
    fi

    xhr_count="$(printf '%s' "$line" | jq -r '(.response.xhr_requests // []) | length' 2>/dev/null || echo 0)"
    if [[ "$xhr_count" =~ ^[0-9]+$ ]] && (( xhr_count > 0 )); then
        return 0
    fi

    url="$(printf '%s' "$line" | jq -r '.request.endpoint // .request.url // .url // empty' 2>/dev/null || true)"
    [[ -n "$url" ]] || return 1
    method="$(printf '%s' "$line" | jq -r '.request.method // "GET"' 2>/dev/null || echo "GET")"
    content_type="$(printf '%s' "$line" | jq -r '.response.headers["content-type"] // .response.headers["Content-Type"] // ""' 2>/dev/null || true)"
    url_path="$(extract_url_path "$url")"
    case_type="$(classify_type "$method" "$url_path" "$content_type" "")"

    case "$case_type" in
        page|api|graphql|form|upload|websocket|unknown)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

ingest_request() {
    local method="${1:-GET}"
    local url="${2:-}"
    local content_type="${3:-}"
    local resp_status="${4:-0}"
    local source_name="${5:-katana}"
    local body_params="{}"
    local cookie_params="{}"
    local query_params path_params url_path case_type params_sig inserted

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
    if is_katana_low_signal_realtime_url "$url"; then
        return 0
    fi

    query_params=$(extract_query_params "$url")
    path_params=$(extract_path_params "$url_path")
    case_type=$(classify_type "$method" "$url_path" "$content_type" "")
    params_sig=$(generate_params_sig "$query_params" "$body_params")

    if ! inserted="$(db_insert_case "$DB_PATH" \
        "$method" "$url" "$url_path" \
        "$query_params" "$body_params" "$path_params" "$cookie_params" \
        "" "" "$content_type" "0" \
        "$resp_status" "" "0" "" \
        "$case_type" "$source_name" "$params_sig")"; then
        return 0
    fi

    inserted=$(printf '%s' "$inserted" | tr -d '[:space:]')
    if [[ "$inserted" =~ ^[0-9]+$ ]] && (( inserted > 0 )); then
        count=$((count + inserted))
        maybe_log_progress
    fi
}

ingest_katana_line() {
    local line="${1:-}"
    local url method content_type resp_status request_json error_text

    [[ -n "$line" ]] || return 0

    error_text="$(printf '%s' "$line" | jq -r '.error // empty' 2>/dev/null || true)"
    if [[ -n "$error_text" ]] && katana_error_is_recoverable_discovery "$error_text"; then
        KATANA_RECOVERABLE_ERROR_LINES=$((KATANA_RECOVERABLE_ERROR_LINES + 1))
    elif katana_line_counts_as_success "$line"; then
        KATANA_SUCCESS_LINES=$((KATANA_SUCCESS_LINES + 1))
        KATANA_LAST_SUCCESS_TS="$(date +%s)"
    fi

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

read_new_output_bytes() {
    local output_file="$1"
    local current_size lines_file remainder_file line

    current_size="$(wc -c < "$output_file" | tr -d '[:space:]')"
    current_size="${current_size:-0}"

    if (( current_size < LAST_OFFSET )); then
        LAST_OFFSET=0
        INGEST_REMAINDER=""
    fi

    if (( current_size == LAST_OFFSET )); then
        return 0
    fi

    KATANA_LAST_OUTPUT_CHANGE_TS="$(date +%s)"

    lines_file="$(mktemp)"
    remainder_file="$(mktemp)"

    python3 - "$output_file" "$LAST_OFFSET" "$current_size" "$INGEST_REMAINDER" "$lines_file" "$remainder_file" <<'PY'
from pathlib import Path
import sys

output_path = Path(sys.argv[1])
start = int(sys.argv[2])
end = int(sys.argv[3])
carry = sys.argv[4].encode("utf-8")
lines_path = Path(sys.argv[5])
remainder_path = Path(sys.argv[6])

data = carry + output_path.read_bytes()[start:end]
lines = []
cursor = 0
while True:
    newline = data.find(b"\n", cursor)
    if newline < 0:
        remainder = data[cursor:]
        break
    line = data[cursor:newline]
    if line.endswith(b"\r"):
        line = line[:-1]
    lines.append(line)
    cursor = newline + 1
else:
    remainder = b""

if lines:
    lines_path.write_bytes(b"\n".join(lines) + b"\n")
else:
    lines_path.write_bytes(b"")
remainder_path.write_bytes(remainder)
PY

    LAST_OFFSET="$current_size"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -n "$line" ]] || continue
        ingest_katana_line "$line"
    done < "$lines_file"

    if [[ -s "$remainder_file" ]]; then
        INGEST_REMAINDER="$(cat "$remainder_file")"
    else
        INGEST_REMAINDER=""
    fi

    rm -f "$lines_file" "$remainder_file"
}

activate_plain_katana_fallback() {
    if [[ "$KATANA_FALLBACK_ACTIVATED" == "1" ]]; then
        return 0
    fi

    echo "[katana_ingest] Activating plain katana fallback after ${KATANA_RECOVERABLE_ERROR_LINES} recoverable hybrid errors and no successful crawl rows"
    stop_katana >/dev/null 2>&1 || true

    local old_enable_hybrid="${KATANA_ENABLE_HYBRID:-1}"
    local old_enable_xhr="${KATANA_ENABLE_XHR:-1}"
    local old_enable_headless="${KATANA_ENABLE_HEADLESS:-1}"
    export KATANA_ENABLE_HYBRID=0
    export KATANA_ENABLE_XHR=0
    export KATANA_ENABLE_HEADLESS=0
    : > "$KATANA_OUTPUT"
    LAST_OFFSET=0
    INGEST_REMAINDER=""
    start_katana "$TARGET" "${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}"
    export KATANA_ENABLE_HYBRID="$old_enable_hybrid"
    export KATANA_ENABLE_XHR="$old_enable_xhr"
    export KATANA_ENABLE_HEADLESS="$old_enable_headless"

    KATANA_FALLBACK_ACTIVATED=1
    KATANA_LAST_OUTPUT_CHANGE_TS="$(date +%s)"
}

maybe_activate_katana_fallback() {
    local now elapsed_since_output elapsed_since_success

    [[ "${KATANA_FALLBACK_ENABLE:-1}" == "1" ]] || return 0
    [[ "$KATANA_INGEST_STARTED_KATANA" == "1" ]] || return 0
    [[ "$KATANA_FALLBACK_ACTIVATED" == "0" ]] || return 0
    [[ "$KATANA_RECOVERABLE_ERROR_LINES" -ge "$KATANA_FALLBACK_RECOVERABLE_THRESHOLD" ]] || return 0
    [[ "$KATANA_SUCCESS_LINES" -eq 0 ]] || return 0

    now="$(date +%s)"
    if [[ "$KATANA_LAST_OUTPUT_CHANGE_TS" -le 0 ]]; then
        return 0
    fi

    elapsed_since_output=$((now - KATANA_LAST_OUTPUT_CHANGE_TS))
    elapsed_since_success=$((now - KATANA_LAST_SUCCESS_TS))

    if (( elapsed_since_output < KATANA_FALLBACK_STALL_SECONDS )); then
        return 0
    fi

    if (( elapsed_since_success < KATANA_FALLBACK_STALL_SECONDS )); then
        return 0
    fi

    activate_plain_katana_fallback
}

# --- Start Katana container unless explicitly skipped for re-ingest/verification ---
if [[ "${KATANA_INGEST_SKIP_START:-0}" != "1" ]]; then
    start_katana "$TARGET" "${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}"
    KATANA_INGEST_STARTED_KATANA=1
    KATANA_LAST_OUTPUT_CHANGE_TS="$(date +%s)"
    KATANA_LAST_SUCCESS_TS="$(date +%s)"
fi

# --- Monitor output and ingest ---
echo "[katana_ingest] Monitoring $KATANA_OUTPUT for crawl results..."

if [[ "${KATANA_INGEST_ONESHOT:-0}" == "1" ]]; then
    read_new_output_bytes "$KATANA_OUTPUT"
    if [[ -n "$INGEST_REMAINDER" ]]; then
        ingest_katana_line "$INGEST_REMAINDER"
        INGEST_REMAINDER=""
    fi
else
    # Katana may leave the newest JSON row unterminated for long stretches. Read only the
    # newly appended bytes on each size change and carry an unfinished trailing row forward
    # until it is completed, instead of re-ingesting the whole file.
    poll_seconds="${KATANA_INGEST_POLL_SECONDS:-2}"
    while true; do
        read_new_output_bytes "$KATANA_OUTPUT"
        maybe_activate_katana_fallback
        if maybe_finish_ingest_loop; then
            break
        fi
        sleep "$poll_seconds"
    done
fi

echo "[katana_ingest] Ingested $count total cases from $TARGET"
