#!/bin/bash
set -euo pipefail

# dispatcher.sh — Zero-token queue consumption engine
# Manages the SQLite case queue without consuming LLM tokens.

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
  echo "  requeue                        Read JSON lines from stdin, insert as pending"
  exit 1
fi

sql() {
  sqlite3 "$DB" ".timeout 5000" "$1"
}

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
    sql "UPDATE cases SET status='error' WHERE id IN (${ID_LIST});"
    echo "Marked error: ${ID_LIST}"
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
      URL_PATH=$(echo "$line" | jq -r '.url_path')
      TYPE=$(echo "$line" | jq -r '.type')
      SOURCE=$(echo "$line" | jq -r '.source')
      QUERY_PARAMS=$(echo "$line" | jq -r '.query_params // ""')
      BODY_PARAMS=$(echo "$line" | jq -r '.body_params // ""')
      PARAMS_KEY_SIG=$(echo "$line" | jq -r '.params_key_sig // ""')

      # Escape single quotes for SQLite
      METHOD="${METHOD//\'/\'\'}"
      URL="${URL//\'/\'\'}"
      URL_PATH="${URL_PATH//\'/\'\'}"
      TYPE="${TYPE//\'/\'\'}"
      SOURCE="${SOURCE//\'/\'\'}"
      QUERY_PARAMS="${QUERY_PARAMS//\'/\'\'}"
      BODY_PARAMS="${BODY_PARAMS//\'/\'\'}"
      PARAMS_KEY_SIG="${PARAMS_KEY_SIG//\'/\'\'}"

      RESULT=$(sql "INSERT OR IGNORE INTO cases (method, url, url_path, type, source, query_params, body_params, params_key_sig, status)
        VALUES ('${METHOD}', '${URL}', '${URL_PATH}', '${TYPE}', '${SOURCE}', '${QUERY_PARAMS}', '${BODY_PARAMS}', '${PARAMS_KEY_SIG}', 'pending');
        SELECT changes();" )

      COUNT=$((COUNT + RESULT))
    done

    echo "Requeued ${COUNT} new case(s)"
    ;;

  *)
    echo "Unknown action: ${ACTION}"
    echo "Usage: $0 <db_path> {stats|fetch|done|error|reset-stale|requeue}"
    exit 1
    ;;
esac
