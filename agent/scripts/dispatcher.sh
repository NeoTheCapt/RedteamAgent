#!/bin/bash
set -euo pipefail

# dispatcher.sh — Zero-token queue consumption engine
# Manages the SQLite case queue without consuming LLM tokens.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/source_queue_filter.sh"

DB="${1:-}"
ACTION="${2:-}"

if [[ -z "$DB" || -z "$ACTION" ]]; then
  echo "Usage: $0 <db_path> <action> [args...]"
  echo ""
  echo "Actions:"
  echo "  stats                          Show queue statistics"
  echo "  fetch <type> <limit> <agent>   Atomic consume batch (JSON output)"
  echo "  done <id_list>                 Mark comma-separated IDs as done"
  echo "  error <id_list>                Mark comma-separated IDs as error"
  echo "  reset-stale <minutes>          Recover stuck processing cases"
  echo "  retry-errors [max_retries]     Retry error cases (default max: 2)"
  echo "  migrate                        Add retry_count column if missing"
  echo "  requeue                        Read JSON lines from stdin, insert as pending"
  exit 1
fi

sql() {
  sqlite3 "$DB" ".timeout 5000" "$1"
}

# Auto-migrate: add retry_count column if missing
sql "ALTER TABLE cases ADD COLUMN retry_count INTEGER DEFAULT 0;" 2>/dev/null || true

case "$ACTION" in
  stats)
    echo "--- Queue Statistics ---"
    sql "SELECT status, type, COUNT(*) as count FROM cases GROUP BY status, type ORDER BY status, type;"
    echo ""
    echo "--- Summary ---"
    sql "SELECT status, COUNT(*) as count FROM cases GROUP BY status ORDER BY status;"
    echo ""
    sql "SELECT 'TOTAL', COUNT(*) FROM cases;"
    ;;

  fetch)
    TYPE="${3:?Missing type argument}"
    LIMIT="${4:?Missing limit argument}"
    AGENT="${5:?Missing agent argument}"

    # Escape single quotes for SQL safety
    TYPE="${TYPE//\'/\'\'}"
    AGENT="${AGENT//\'/\'\'}"
    # Validate LIMIT is numeric
    if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
      echo "ERROR: limit must be a positive integer" >&2
      exit 1
    fi

    sqlite3 "$DB" ".timeout 5000" -json "
      UPDATE cases
      SET status = 'processing',
          assigned_agent = '${AGENT}',
          consumed_at = datetime('now')
      WHERE id IN (
        SELECT id FROM cases
        WHERE status = 'pending' AND type = '${TYPE}'
        LIMIT ${LIMIT}
      )
      RETURNING *;
    "
    ;;

  done)
    ID_LIST="${3:?Missing id_list argument}"
    # Validate ID_LIST contains only digits and commas
    if ! [[ "$ID_LIST" =~ ^[0-9,]+$ ]]; then
      echo "ERROR: id_list must contain only numeric IDs separated by commas" >&2
      exit 1
    fi
    sql "UPDATE cases SET status='done' WHERE id IN (${ID_LIST});"
    echo "Marked done: ${ID_LIST}"
    ;;

  error)
    ID_LIST="${3:?Missing id_list argument}"
    # Validate ID_LIST contains only digits and commas
    if ! [[ "$ID_LIST" =~ ^[0-9,]+$ ]]; then
      echo "ERROR: id_list must contain only numeric IDs separated by commas" >&2
      exit 1
    fi
    sql "UPDATE cases SET status='error', retry_count = COALESCE(retry_count,0) + 1 WHERE id IN (${ID_LIST});"
    echo "Marked error: ${ID_LIST}"
    ;;

  migrate)
    sql "ALTER TABLE cases ADD COLUMN retry_count INTEGER DEFAULT 0;" 2>/dev/null || true
    ;;

  retry-errors)
    MAX_RETRIES="${3:-2}"
    if ! [[ "$MAX_RETRIES" =~ ^[0-9]+$ ]]; then
      echo "ERROR: max_retries must be a positive integer" >&2
      exit 1
    fi
    BEFORE=$(sql "SELECT COUNT(*) FROM cases WHERE status='error' AND COALESCE(retry_count,0) < ${MAX_RETRIES};")
    sql "UPDATE cases SET status='pending', assigned_agent=NULL, consumed_at=NULL WHERE status='error' AND COALESCE(retry_count,0) < ${MAX_RETRIES};"
    echo "Retried ${BEFORE} error case(s) (max retries: ${MAX_RETRIES})"
    ;;

  reset-stale)
    MINUTES="${3:?Missing minutes argument}"
    # Validate MINUTES is numeric
    if ! [[ "$MINUTES" =~ ^[0-9]+$ ]]; then
      echo "ERROR: minutes must be a positive integer" >&2
      exit 1
    fi
    BEFORE=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND consumed_at < datetime('now', '-${MINUTES} minutes');")
    sql "UPDATE cases SET status='pending', assigned_agent=NULL, consumed_at=NULL WHERE status='processing' AND consumed_at < datetime('now', '-${MINUTES} minutes');"
    echo "Reset ${BEFORE} stale case(s) (stuck > ${MINUTES} min)"
    ;;

  requeue)
    COUNT=0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue

      METHOD=$(echo "$line" | jq -r '.method')
      URL=$(echo "$line" | jq -r '.url')
      URL_PATH=$(echo "$line" | jq -r '.url_path // empty')
      TYPE=$(echo "$line" | jq -r '.type')
      SOURCE=$(echo "$line" | jq -r '.source // "requeue"')
      QUERY_PARAMS=$(echo "$line" | jq -r 'if .query_params == null then empty elif (.query_params | type) == "string" then .query_params else (.query_params | tojson) end')
      BODY_PARAMS=$(echo "$line" | jq -r 'if .body_params == null then empty elif (.body_params | type) == "string" then .body_params else (.body_params | tojson) end')
      PATH_PARAMS=$(echo "$line" | jq -r 'if .path_params == null then empty elif (.path_params | type) == "string" then .path_params else (.path_params | tojson) end')
      COOKIE_PARAMS=$(echo "$line" | jq -r 'if .cookie_params == null then empty elif (.cookie_params | type) == "string" then .cookie_params else (.cookie_params | tojson) end')
      HEADERS=$(echo "$line" | jq -r 'if .headers == null then empty elif (.headers | type) == "string" then .headers else (.headers | tojson) end')
      BODY=$(echo "$line" | jq -r '.body // ""')
      CONTENT_TYPE=$(echo "$line" | jq -r '.content_type // ""')
      CONTENT_LENGTH=$(echo "$line" | jq -r '.content_length // 0')
      RESPONSE_STATUS=$(echo "$line" | jq -r '.response_status // 0')
      RESPONSE_HEADERS=$(echo "$line" | jq -r 'if .response_headers == null then empty elif (.response_headers | type) == "string" then .response_headers else (.response_headers | tojson) end')
      RESPONSE_SIZE=$(echo "$line" | jq -r '.response_size // 0')
      RESPONSE_SNIPPET=$(echo "$line" | jq -r '.response_snippet // ""')
      PARAMS_KEY_SIG=$(echo "$line" | jq -r '.params_key_sig // empty')

      [[ "$METHOD" == "null" || -z "$METHOD" ]] && METHOD="GET"
      [[ "$URL" == "null" ]] && URL=""
      [[ "$TYPE" == "null" || -z "$TYPE" ]] && TYPE="unknown"
      [[ "$SOURCE" == "null" || -z "$SOURCE" ]] && SOURCE="requeue"
      [[ -z "$URL_PATH" ]] && URL_PATH="$(extract_url_path "$URL")"
      [[ -z "$QUERY_PARAMS" ]] && QUERY_PARAMS="$(extract_query_params "$URL" | jq -c '.')"
      [[ -z "$BODY_PARAMS" ]] && BODY_PARAMS="{}"
      [[ -z "$PATH_PARAMS" ]] && PATH_PARAMS="$(extract_path_params "$URL_PATH" | jq -c '.')"
      [[ -z "$COOKIE_PARAMS" ]] && COOKIE_PARAMS="{}"
      [[ -z "$HEADERS" ]] && HEADERS="{}"
      [[ -z "$RESPONSE_HEADERS" ]] && RESPONSE_HEADERS="{}"
      [[ -z "$PARAMS_KEY_SIG" ]] && PARAMS_KEY_SIG="$(generate_params_sig "$QUERY_PARAMS" "$BODY_PARAMS")"

      if [[ -z "$URL" || -z "$URL_PATH" ]]; then
        echo "ERROR: requeue line missing usable url/url_path" >&2
        exit 1
      fi

      [[ "$CONTENT_LENGTH" =~ ^-?[0-9]+$ ]] || CONTENT_LENGTH=0
      [[ "$RESPONSE_STATUS" =~ ^-?[0-9]+$ ]] || RESPONSE_STATUS=0
      [[ "$RESPONSE_SIZE" =~ ^-?[0-9]+$ ]] || RESPONSE_SIZE=0

      if ! should_enqueue_case "$SOURCE" "$TYPE" "$METHOD" "$URL" "$URL_PATH"; then
        continue
      fi

      # Escape single quotes for SQLite
      METHOD="${METHOD//\'/\'\'}"
      URL="${URL//\'/\'\'}"
      URL_PATH="${URL_PATH//\'/\'\'}"
      TYPE="${TYPE//\'/\'\'}"
      SOURCE="${SOURCE//\'/\'\'}"
      QUERY_PARAMS="${QUERY_PARAMS//\'/\'\'}"
      BODY_PARAMS="${BODY_PARAMS//\'/\'\'}"
      PATH_PARAMS="${PATH_PARAMS//\'/\'\'}"
      COOKIE_PARAMS="${COOKIE_PARAMS//\'/\'\'}"
      HEADERS="${HEADERS//\'/\'\'}"
      BODY="${BODY//\'/\'\'}"
      CONTENT_TYPE="${CONTENT_TYPE//\'/\'\'}"
      RESPONSE_HEADERS="${RESPONSE_HEADERS//\'/\'\'}"
      RESPONSE_SNIPPET="${RESPONSE_SNIPPET//\'/\'\'}"
      PARAMS_KEY_SIG="${PARAMS_KEY_SIG//\'/\'\'}"

      RESULT=$(sql "INSERT OR IGNORE INTO cases (
          method, url, url_path,
          query_params, body_params, path_params, cookie_params,
          headers, body, content_type, content_length,
          response_status, response_headers, response_size, response_snippet,
          type, source, status, params_key_sig,
          assigned_agent, consumed_at
        ) VALUES (
          '${METHOD}', '${URL}', '${URL_PATH}',
          '${QUERY_PARAMS}', '${BODY_PARAMS}', '${PATH_PARAMS}', '${COOKIE_PARAMS}',
          '${HEADERS}', '${BODY}', '${CONTENT_TYPE}', ${CONTENT_LENGTH},
          ${RESPONSE_STATUS}, '${RESPONSE_HEADERS}', ${RESPONSE_SIZE}, '${RESPONSE_SNIPPET}',
          '${TYPE}', '${SOURCE}', 'pending', '${PARAMS_KEY_SIG}',
          NULL, NULL
        );
        SELECT changes();" )

      COUNT=$((COUNT + RESULT))
    done

    echo "Requeued ${COUNT} new case(s)"
    ;;

  *)
    echo "Unknown action: ${ACTION}"
    echo "Usage: $0 <db_path> {stats|fetch|done|error|reset-stale|retry-errors|migrate|requeue}"
    exit 1
    ;;
esac
