#!/bin/bash
set -euo pipefail

# dispatcher.sh — Zero-token queue consumption engine
# Manages the SQLite case queue without consuming LLM tokens.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/params.sh"
source "$SCRIPT_DIR/lib/placeholders.sh"
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

fetch_priority_order_clause() {
  local queue_type="$(_source_queue_lower "${1:-}")"

  cat <<'EOF'
ORDER BY
  (
    CASE lower(source)
      WHEN 'exploit-developer' THEN 500
      WHEN 'katana-xhr' THEN 460
      WHEN 'katana' THEN 430
      WHEN 'vulnerability-analyst' THEN 380
      WHEN 'source-analyzer' THEN 280
      WHEN 'recon-specialist' THEN 220
      ELSE 0
    END
    + CASE upper(method)
        WHEN 'POST' THEN 180
        WHEN 'PUT' THEN 170
        WHEN 'PATCH' THEN 160
        WHEN 'DELETE' THEN 150
        ELSE 0
      END
    + CASE WHEN query_params IS NOT NULL AND query_params NOT IN ('', '{}', 'null') THEN 40 ELSE 0 END
    + CASE WHEN body_params IS NOT NULL AND body_params NOT IN ('', '{}', 'null') THEN 70 ELSE 0 END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%/admin%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%administration%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%/manage%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%/config%'
        THEN 180 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%login%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%logout%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%signin%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%signup%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%register%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%auth%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%session%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%token%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%jwt%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%whoami%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%profile%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%password%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%reset%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%recover%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%forgot%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%security%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%verify%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%2fa%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%mfa%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%otp%'
        THEN 170 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%wallet%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%payment%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%payout%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%billing%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%invoice%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%bank%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%card%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%address%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%order%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%account%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%kyc%'
        THEN 150 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%upload%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%file%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%document%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%export%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%import%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%backup%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%report%'
        THEN 130 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%graphql%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%swagger%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%openapi%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%api-doc%'
        THEN 90 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%search%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%query%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%filter%'
        THEN 25 ELSE 0
      END
  ) DESC,
  id ASC
EOF

  case "$queue_type" in
    api|graphql|form|upload|websocket|api-spec)
      ;;
    page|data|javascript|stylesheet|unknown|*)
      ;;
  esac
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

    IN_FLIGHT_FOR_AGENT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='${AGENT}';")
    if [[ "${IN_FLIGHT_FOR_AGENT:-0}" =~ ^[0-9]+$ ]] && (( IN_FLIGHT_FOR_AGENT > 0 )); then
      echo "[]"
      echo "Refusing fetch for ${AGENT}: ${IN_FLIGHT_FOR_AGENT} case(s) already processing" >&2
      exit 0
    fi

    ORDER_CLAUSE="$(fetch_priority_order_clause "$TYPE")"

    sqlite3 "$DB" ".timeout 5000" -json "
      UPDATE cases
      SET status = 'processing',
          assigned_agent = '${AGENT}',
          consumed_at = datetime('now')
      WHERE id IN (
        SELECT id FROM cases
        WHERE status = 'pending' AND type = '${TYPE}'
        ${ORDER_CLAUSE}
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
      if contains_queue_placeholder "$URL" || contains_queue_placeholder "$URL_PATH"; then
        continue
      fi
      [[ -z "$QUERY_PARAMS" ]] && QUERY_PARAMS="$(extract_query_params "$URL" | jq -c '.')"
      [[ -z "$BODY_PARAMS" ]] && BODY_PARAMS="{}"
      [[ -z "$PATH_PARAMS" ]] && PATH_PARAMS="$(extract_path_params "$URL_PATH" | jq -c '.')"
      [[ -z "$COOKIE_PARAMS" ]] && COOKIE_PARAMS="{}"
      [[ -z "$HEADERS" ]] && HEADERS="{}"
      [[ -z "$RESPONSE_HEADERS" ]] && RESPONSE_HEADERS="{}"
      [[ -z "$PARAMS_KEY_SIG" ]] && PARAMS_KEY_SIG="$(generate_params_sig "$QUERY_PARAMS" "$BODY_PARAMS" "$URL")"

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

      REQUEUE_STATUS="pending"
      case "$TYPE" in
        image|video|font|archive)
          REQUEUE_STATUS="skipped"
          ;;
      esac

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

      RESULT=$(sql "INSERT INTO cases (
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
          '${TYPE}', '${SOURCE}', '${REQUEUE_STATUS}', '${PARAMS_KEY_SIG}',
          NULL, NULL
        )
        ON CONFLICT(method, url_path, params_key_sig) DO UPDATE SET
          url = excluded.url,
          query_params = excluded.query_params,
          body_params = excluded.body_params,
          path_params = excluded.path_params,
          cookie_params = excluded.cookie_params,
          headers = excluded.headers,
          body = excluded.body,
          content_type = excluded.content_type,
          content_length = excluded.content_length,
          response_status = excluded.response_status,
          response_headers = excluded.response_headers,
          response_size = excluded.response_size,
          response_snippet = excluded.response_snippet,
          type = excluded.type,
          source = excluded.source,
          status = CASE
            WHEN excluded.type IN ('image', 'video', 'font', 'archive') THEN 'skipped'
            ELSE 'pending'
          END,
          assigned_agent = NULL,
          consumed_at = NULL
        WHERE cases.type = 'unknown'
          AND excluded.type != 'unknown'
          AND cases.status IN ('pending', 'processing', 'error');
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
