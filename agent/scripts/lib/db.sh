#!/usr/bin/env bash
# db.sh — Database helper library for the case collection pipeline.
# Usage: source scripts/lib/db.sh

# Escape single quotes for safe SQL string interpolation.
# Replaces ' with '' per SQL standard.
_db_escape() {
    printf '%s' "$1" | sed "s/'/''/g"
}

_db_is_transient_error() {
    local message="${1:-}"
    [[ "$message" == *"database is locked"* ]] \
        || [[ "$message" == *"database schema is locked"* ]] \
        || [[ "$message" == *"database table is locked"* ]] \
        || [[ "$message" == *"database is busy"* ]] \
        || [[ "$message" == *"database table is busy"* ]]
}

_db_sqlite_with_retry() {
    local format="$1"
    local db_path="$2"
    local input_sql="$3"
    local max_attempts="${DB_RETRY_ATTEMPTS:-4}"
    local retry_sleep="${DB_RETRY_SLEEP_SECONDS:-1}"
    local attempt=1
    local stdout_file stderr_file stderr_text

    while true; do
        stdout_file="$(mktemp)"
        stderr_file="$(mktemp)"

        if [[ "$format" == "json" ]]; then
            if printf '.timeout 5000\n%s\n' "$input_sql" | sqlite3 -json "$db_path" >"$stdout_file" 2>"$stderr_file"; then
                cat "$stdout_file"
                rm -f "$stdout_file" "$stderr_file"
                return 0
            fi
        else
            if printf '.timeout 5000\n%s\n' "$input_sql" | sqlite3 "$db_path" >"$stdout_file" 2>"$stderr_file"; then
                cat "$stdout_file"
                rm -f "$stdout_file" "$stderr_file"
                return 0
            fi
        fi

        stderr_text="$(cat "$stderr_file")"
        rm -f "$stdout_file" "$stderr_file"

        if _db_is_transient_error "$stderr_text" && (( attempt < max_attempts )); then
            sleep "$retry_sleep"
            attempt=$((attempt + 1))
            continue
        fi

        [[ -n "$stderr_text" ]] && printf '%s\n' "$stderr_text" >&2
        return 1
    done
}

# db_init <db_path>
# Verify database exists; ensure WAL mode and busy_timeout are set.
db_init() {
    local db_path="$1"

    if [[ -z "$db_path" ]]; then
        echo "db_init: db_path is required" >&2
        return 1
    fi

    if [[ ! -f "$db_path" ]]; then
        echo "db_init: database not found: $db_path" >&2
        return 1
    fi

    _db_sqlite_with_retry text "$db_path" "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;" >/dev/null
}

# db_query <db_path> <sql>
# Execute a query with pragmas pre-set, return JSON output.
db_query() {
    local db_path="$1"
    local sql="$2"

    if [[ -z "$db_path" || -z "$sql" ]]; then
        echo "db_query: db_path and sql are required" >&2
        return 1
    fi

    _db_sqlite_with_retry json "$db_path" "$sql"
}

# db_exec <db_path> <sql>
# Execute a non-query statement with pragmas pre-set.
db_exec() {
    local db_path="$1"
    local sql="$2"

    if [[ -z "$db_path" || -z "$sql" ]]; then
        echo "db_exec: db_path and sql are required" >&2
        return 1
    fi

    _db_sqlite_with_retry text "$db_path" "$sql"
}

# db_insert_case <db_path> <method> <url> <url_path> <query_params> <body_params>
#   <path_params> <cookie_params> <headers> <body> <content_type> <content_length>
#   <response_status> <response_headers> <response_size> <response_snippet>
#   <type> <source> <params_key_sig>
# Insert a case with INSERT OR IGNORE for dedup.
# Auto-sets status to 'skipped' for non-consumable types (image, video, font, archive).
# Prints the SQLite changes() count so callers can distinguish inserted rows from dedup no-ops.
db_insert_case() {
    local db_path="$1"
    local method="$2"
    local url="$3"
    local url_path="$4"
    local query_params="$5"
    local body_params="$6"
    local path_params="$7"
    local cookie_params="$8"
    local headers="$9"
    local body="${10}"
    local content_type="${11}"
    local content_length="${12}"
    local response_status="${13}"
    local response_headers="${14}"
    local response_size="${15}"
    local response_snippet="${16}"
    local type="${17}"
    local source="${18}"
    local params_key_sig="${19}"

    if [[ -z "$db_path" ]]; then
        echo "db_insert_case: db_path is required" >&2
        return 1
    fi

    # Validate required fields — reject null/empty values
    if [[ -z "$url" || "$url" == "null" ]]; then
        echo "db_insert_case: skipping case with empty/null url" >&2
        return 1
    fi
    if [[ -z "$url_path" || "$url_path" == "null" ]]; then
        # Try to extract url_path from url as fallback
        url_path=$(echo "$url" | sed 's|https\?://[^/]*||' | sed 's|\?.*||' | sed 's|#.*||')
        if [[ -z "$url_path" || "$url_path" == "null" ]]; then
            echo "db_insert_case: skipping case with empty/null url_path" >&2
            return 1
        fi
    fi
    if [[ -z "$method" || "$method" == "null" ]]; then
        method="GET"
    fi

    # Determine status based on type
    local status="pending"
    case "$type" in
        image|video|font|archive)
            status="skipped"
            ;;
    esac

    # Escape all string values for SQL
    local e_method e_url e_url_path e_query_params e_body_params e_path_params
    local e_cookie_params e_headers e_body e_content_type e_response_headers
    local e_response_snippet e_type e_source e_params_key_sig

    e_method=$(_db_escape "$method")
    e_url=$(_db_escape "$url")
    e_url_path=$(_db_escape "$url_path")
    e_query_params=$(_db_escape "$query_params")
    e_body_params=$(_db_escape "$body_params")
    e_path_params=$(_db_escape "$path_params")
    e_cookie_params=$(_db_escape "$cookie_params")
    e_headers=$(_db_escape "$headers")
    e_body=$(_db_escape "$body")
    e_content_type=$(_db_escape "$content_type")
    e_response_headers=$(_db_escape "$response_headers")
    e_response_snippet=$(_db_escape "$response_snippet")
    e_type=$(_db_escape "$type")
    e_source=$(_db_escape "$source")
    e_params_key_sig=$(_db_escape "$params_key_sig")

    local sql="INSERT OR IGNORE INTO cases (
    method, url, url_path,
    query_params, body_params, path_params, cookie_params,
    headers, body, content_type, content_length,
    response_status, response_headers, response_size, response_snippet,
    type, source, status, params_key_sig
) VALUES (
    '${e_method}', '${e_url}', '${e_url_path}',
    '${e_query_params}', '${e_body_params}', '${e_path_params}', '${e_cookie_params}',
    '${e_headers}', '${e_body}', '${e_content_type}', ${content_length:-0},
    ${response_status:-0}, '${e_response_headers}', ${response_size:-0}, '${e_response_snippet}',
    '${e_type}', '${e_source}', '${status}', '${e_params_key_sig}'
);"

    _db_sqlite_with_retry text "$db_path" "$sql
SELECT changes();"
}
