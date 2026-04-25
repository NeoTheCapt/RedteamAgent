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
  echo "  stats                          Show queue statistics (by status/type)"
  echo "  stats-by-stage                 Show queue statistics by (stage, type)"
  echo "  fetch <type> <limit> <agent>   Legacy: fetch by type, sets status=processing"
  echo "  fetch-by-stage <stage> <type> <limit> <agent>"
  echo "                                 Stage-aware fetch (preferred); cases must"
  echo "                                 be at <stage> AND of <type>; sets status=processing"
  echo "  done <id_list> [--stage S]     Mark IDs as done; optional --stage advances pipeline"
  echo "  error <id_list>                Mark comma-separated IDs as error"
  echo "  set-stage <id_list> <stage>    Bulk update stage column (no status change)"
  echo "  boost-priority <id_list> <delta>"
  echo "                                 Adjust predicted_value column (signed int);"
  echo "                                 + delta promotes case to front of next fetch"
  echo "  reset-stale <minutes>          Recover stuck processing cases"
  echo "  retry-errors [max_retries]     Retry error cases (default max: 2)"
  echo "  migrate                        Add missing schema columns (idempotent)"
  echo "  requeue [id_list ...] [reason] Requeue existing case IDs or read JSON lines from stdin"
  echo ""
  echo "Stage values (pipeline state machine):"
  echo "  ingested         freshly discovered, needs first-pass triage"
  echo "  source_analyzed  source-analyzer ran (may set vuln_candidate)"
  echo "  api_tested       vulnerability-analyst ran, no vuln found"
  echo "  vuln_confirmed   exploitable; ready for exploit-developer"
  echo "  exploited        finding written end-to-end"
  echo "  clean            tested, no vuln, terminal"
  echo "  errored          terminal failure (use 'error' action)"
  exit 1
fi

sql() {
  sqlite3 "$DB" ".timeout 5000" "$1"
}

ensure_cases_column() {
  local name="$1"
  local definition="$2"
  local present
  present="$(sql "SELECT COUNT(*) FROM pragma_table_info('cases') WHERE name='${name}';" 2>/dev/null || printf '0')"
  if [[ "${present:-0}" != "1" ]]; then
    sql "ALTER TABLE cases ADD COLUMN ${name} ${definition};" 2>/dev/null || true
  fi
}

is_bookkeeping_suffix_token() {
  case "$1" in
    operator|recon-specialist|source-analyzer|vulnerability-analyst|exploit-developer|fuzzer|osint-analyst|report-writer|done|error|pending|processing|requeued|completed|skipped)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_id_list() {
  if (($# == 0)); then
    echo "ERROR: id_list must contain at least one numeric ID" >&2
    exit 1
  fi

  local token
  local normalized=()
  local ignored_suffixes=()
  local saw_suffix=0
  for token in "$@"; do
    token="${token// /}"
    token="${token#,}"
    token="${token%,}"
    [[ -z "$token" ]] && continue
    IFS=',' read -r -a parts <<< "$token"
    local part
    for part in "${parts[@]}"; do
      [[ -z "$part" ]] && continue
      if [[ "$part" =~ ^[0-9]+$ ]]; then
        if (( saw_suffix )); then
          echo "ERROR: id_list must contain only numeric IDs separated by commas or spaces" >&2
          exit 1
        fi
        normalized+=("$part")
        continue
      fi
      if ((${#normalized[@]} > 0)) && is_bookkeeping_suffix_token "$part"; then
        saw_suffix=1
        ignored_suffixes+=("$part")
        continue
      fi
      if (( saw_suffix )); then
        ignored_suffixes+=("$part")
        continue
      fi
      echo "ERROR: id_list must contain only numeric IDs separated by commas or spaces" >&2
      exit 1
    done
  done

  if ((${#normalized[@]} == 0)); then
    echo "ERROR: id_list must contain at least one numeric ID" >&2
    exit 1
  fi

  if ((${#ignored_suffixes[@]} > 0)); then
    printf 'WARN: ignoring trailing bookkeeping token(s): %s\n' "${ignored_suffixes[*]}" >&2
  fi

  local joined
  printf -v joined '%s,' "${normalized[@]}"
  echo "${joined%,}"
}

fetch_priority_order_clause() {
  local queue_type="$(_source_queue_lower "${1:-}")"

  cat <<'EOF'
ORDER BY
  (
    CASE lower(source)
      WHEN 'exploit-developer' THEN 500
      WHEN 'katana-xhr' THEN 460
      WHEN 'operator-surface-coverage' THEN 445
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
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%feedback%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%review%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%comment%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%rating%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%cart%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%basket%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%checkout%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%privacy%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%policy%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%terms%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%legal%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%sandbox%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%playground%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%demo%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%lab%'
        THEN 120 ELSE 0
      END
    + CASE
        WHEN lower(coalesce(nullif(url_path, ''), url)) LIKE '%search%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%query%'
          OR lower(coalesce(nullif(url_path, ''), url)) LIKE '%filter%'
        THEN 25 ELSE 0
      END
    + coalesce(predicted_value, 0) * 5
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

# Auto-migrate legacy dispatcher columns when resuming older cases.db snapshots.
ensure_cases_column "method" "TEXT"
ensure_cases_column "url" "TEXT"
ensure_cases_column "url_path" "TEXT"
ensure_cases_column "source" "TEXT"
ensure_cases_column "query_params" "TEXT"
ensure_cases_column "body_params" "TEXT"
ensure_cases_column "assigned_agent" "TEXT"
ensure_cases_column "consumed_at" "TEXT"
sql "ALTER TABLE cases ADD COLUMN retry_count INTEGER DEFAULT 0;" 2>/dev/null || true

# Pipeline stage column (added 2026-04-25). Lets cases progress through
# discrete pipeline stages independently of the legacy phase flag, so
# multiple subagents can work on different cases in different stages
# concurrently. Backfill existing rows: anything that was ever 'done' is
# treated as 'clean' (already terminal, won't be re-dispatched);
# everything else (pending/processing/error) starts at 'ingested' so the
# new pipeline picks it up.
ensure_cases_column "stage" "TEXT NOT NULL DEFAULT 'ingested'"
sql "UPDATE cases SET stage='clean' WHERE status='done' AND (stage IS NULL OR stage='ingested' OR stage='');" 2>/dev/null || true
sql "UPDATE cases SET stage='ingested' WHERE stage IS NULL OR stage='';" 2>/dev/null || true

# Per-case priority hint (optional; used by fetch ordering). Higher = sooner;
# negative deprioritizes (no `>0` clamp).
ensure_cases_column "predicted_value" "INTEGER NOT NULL DEFAULT 0"

# Verify migration outcome — surface failures instead of letting downstream
# code SELECT against a non-existent column. We swallow ALTER TABLE errors
# above (idempotent re-runs hit "duplicate column name" which is fine), but
# the column MUST exist after the call; if it doesn't, the DB is corrupt
# or the user's sqlite3 is too old, and we should fail loudly.
for required_col in stage predicted_value; do
  present="$(sql "SELECT COUNT(*) FROM pragma_table_info('cases') WHERE name='${required_col}';" 2>/dev/null || printf '0')"
  if [[ "${present:-0}" != "1" ]]; then
    echo "FATAL: cases.db missing required column '${required_col}' after migration; aborting." >&2
    echo "       check sqlite3 version (need ≥3.35 for ALTER TABLE ... ADD COLUMN with DEFAULT)" >&2
    exit 2
  fi
done

_validate_stage() {
  case "$1" in
    ingested|source_analyzed|api_tested|vuln_confirmed|exploited|clean|errored)
      return 0 ;;
    *)
      echo "ERROR: invalid stage '$1' (allowed: ingested|source_analyzed|api_tested|vuln_confirmed|exploited|clean|errored)" >&2
      return 1 ;;
  esac
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

  stats-by-stage)
    echo "--- Queue Statistics by Stage ---"
    sql "SELECT stage, type, COUNT(*) as count FROM cases GROUP BY stage, type ORDER BY stage, type;"
    echo ""
    echo "--- Stage Summary ---"
    sql "SELECT stage, COUNT(*) as count FROM cases GROUP BY stage ORDER BY stage;"
    echo ""
    echo "--- Active vs Terminal ---"
    sql "
      SELECT 'active (ingested|source_analyzed|vuln_confirmed)' as bucket, COUNT(*)
        FROM cases WHERE stage IN ('ingested','source_analyzed','vuln_confirmed')
      UNION ALL
      SELECT 'in-flight (processing)', COUNT(*) FROM cases WHERE status='processing'
      UNION ALL
      SELECT 'terminal (clean|exploited|errored|api_tested)', COUNT(*)
        FROM cases WHERE stage IN ('clean','exploited','errored','api_tested')
      UNION ALL
      SELECT 'TOTAL', COUNT(*) FROM cases;"
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

    # Per-(agent, type) in-flight guard so the same agent can be working
    # on different types concurrently — supports the streaming-pipeline
    # design where source-analyzer can be at ingested-javascript and
    # ingested-page in the same operator turn.
    IN_FLIGHT_FOR_AGENT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='${AGENT}' AND type='${TYPE}';")
    if [[ "${IN_FLIGHT_FOR_AGENT:-0}" =~ ^[0-9]+$ ]] && (( IN_FLIGHT_FOR_AGENT > 0 )); then
      echo "[]"
      echo "Refusing fetch for ${AGENT} (type=${TYPE}): ${IN_FLIGHT_FOR_AGENT} case(s) already processing" >&2
      exit 0
    fi

    ORDER_CLAUSE="$(fetch_priority_order_clause "$TYPE")"

    # Legacy fetch: pulls 'pending' cases regardless of stage. Kept for
    # backward compatibility; new code should use fetch-by-stage to gate
    # per pipeline stage. The legacy path defaults to ingested-stage
    # cases so it doesn't accidentally re-dispatch already-processed
    # work that's at a later stage (e.g. vuln_confirmed shouldn't be
    # eligible for source-analyzer just because it's pending again).
    sqlite3 "$DB" ".timeout 5000" -json "
      UPDATE cases
      SET status = 'processing',
          assigned_agent = '${AGENT}',
          consumed_at = datetime('now')
      WHERE id IN (
        SELECT id FROM cases
        WHERE status = 'pending' AND type = '${TYPE}'
              AND stage IN ('ingested', 'source_analyzed', 'vuln_confirmed')
        ${ORDER_CLAUSE}
        LIMIT ${LIMIT}
      )
      RETURNING *;
    "
    ;;

  fetch-by-stage)
    STAGE="${3:?Missing stage argument}"
    TYPE="${4:?Missing type argument}"
    LIMIT="${5:?Missing limit argument}"
    AGENT="${6:?Missing agent argument}"

    if ! _validate_stage "$STAGE"; then
      exit 1
    fi
    TYPE="${TYPE//\'/\'\'}"
    AGENT="${AGENT//\'/\'\'}"
    STAGE_ESC="${STAGE//\'/\'\'}"
    if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
      echo "ERROR: limit must be a positive integer" >&2
      exit 1
    fi

    # Per-(agent, type, stage) in-flight guard. Lets the same agent run
    # on different (stage, type) combos concurrently — exactly the
    # cross-stage parallelism Rule 1 of operator-core.md promises.
    IN_FLIGHT_FOR_AGENT=$(sql "SELECT COUNT(*) FROM cases WHERE status='processing' AND assigned_agent='${AGENT}' AND type='${TYPE}' AND stage='${STAGE_ESC}';")
    if [[ "${IN_FLIGHT_FOR_AGENT:-0}" =~ ^[0-9]+$ ]] && (( IN_FLIGHT_FOR_AGENT > 0 )); then
      echo "[]"
      echo "Refusing fetch for ${AGENT} (stage=${STAGE} type=${TYPE}): ${IN_FLIGHT_FOR_AGENT} case(s) already processing" >&2
      exit 0
    fi

    ORDER_CLAUSE="$(fetch_priority_order_clause "$TYPE")"

    # Stage-aware fetch: cases must be at the requested stage AND of the
    # requested type AND status=pending. Sets status=processing and
    # assigned_agent. Stage column is NOT changed here — stage transition
    # is the subagent's responsibility (via 'done --stage' or
    # 'set-stage') so the operator can audit transitions explicitly.
    sqlite3 "$DB" ".timeout 5000" -json "
      UPDATE cases
      SET status = 'processing',
          assigned_agent = '${AGENT}',
          consumed_at = datetime('now')
      WHERE id IN (
        SELECT id FROM cases
        WHERE status = 'pending' AND type = '${TYPE}' AND stage = '${STAGE_ESC}'
        ${ORDER_CLAUSE}
        LIMIT ${LIMIT}
      )
      RETURNING *;
    "
    ;;

  done)
    shift 2
    # Optional `--stage <stage>` flag: advance pipeline at the same time.
    # Without --stage, status flips to 'done' but stage is unchanged
    # (legacy behaviour). With --stage, stage column is updated atomically
    # and status flips to 'pending' if the new stage is non-terminal so
    # the next subagent can pick it up; status flips to 'done' if the new
    # stage is terminal (clean / exploited / errored).
    NEW_STAGE=""
    DONE_ARGS=()
    while (($#)); do
      case "$1" in
        --stage)
          NEW_STAGE="${2:?Missing stage value after --stage}"
          shift 2
          ;;
        *)
          DONE_ARGS+=("$1")
          shift
          ;;
      esac
    done

    if [[ -n "$NEW_STAGE" ]]; then
      if ! _validate_stage "$NEW_STAGE"; then
        exit 1
      fi
    fi

    if ((${#DONE_ARGS[@]} == 0)); then
      echo "ERROR: done requires at least one numeric ID" >&2
      exit 1
    fi
    ID_LIST="$(normalize_id_list "${DONE_ARGS[@]}")"
    if [[ -n "$NEW_STAGE" ]]; then
      case "$NEW_STAGE" in
        clean|exploited|errored)
          # Terminal: status=done, stage=<terminal>
          sql "UPDATE cases SET status='done', stage='${NEW_STAGE}' WHERE id IN (${ID_LIST});"
          echo "Marked done (stage=${NEW_STAGE}, terminal): ${ID_LIST}"
          ;;
        *)
          # Non-terminal stage advance: set stage and clear processing so
          # the next subagent can fetch by the new stage.
          sql "UPDATE cases SET status='pending', stage='${NEW_STAGE}', assigned_agent=NULL, consumed_at=NULL WHERE id IN (${ID_LIST});"
          echo "Advanced stage=${NEW_STAGE} (re-pending for next stage): ${ID_LIST}"
          ;;
      esac
    else
      sql "UPDATE cases SET status='done' WHERE id IN (${ID_LIST});"
      echo "Marked done: ${ID_LIST}"
    fi
    ;;

  set-stage)
    shift 2
    if (($# < 2)); then
      echo "Usage: dispatcher.sh <db> set-stage <id_list> <stage>" >&2
      exit 1
    fi
    NEW_STAGE="${@: -1}"
    if ! _validate_stage "$NEW_STAGE"; then
      exit 1
    fi
    SET_ARGS=("${@:1:$#-1}")
    ID_LIST="$(normalize_id_list "${SET_ARGS[@]}")"
    sql "UPDATE cases SET stage='${NEW_STAGE}' WHERE id IN (${ID_LIST});"
    echo "Set stage=${NEW_STAGE} for: ${ID_LIST}"
    ;;

  boost-priority)
    shift 2
    # Usage: boost-priority <id_list> <delta>
    # delta is added to predicted_value (signed integer). Subagents emitting
    # REQUEUE_CANDIDATE with strong signal can call this to push the case
    # to the front of the next fetch. Operator can also use it to suppress
    # noise (negative delta).
    if (($# < 2)); then
      echo "Usage: dispatcher.sh <db> boost-priority <id_list> <delta>" >&2
      exit 1
    fi
    DELTA="${@: -1}"
    if ! [[ "$DELTA" =~ ^-?[0-9]+$ ]]; then
      echo "ERROR: delta must be a signed integer" >&2
      exit 1
    fi
    BOOST_ARGS=("${@:1:$#-1}")
    ID_LIST="$(normalize_id_list "${BOOST_ARGS[@]}")"
    sql "UPDATE cases SET predicted_value = COALESCE(predicted_value, 0) + (${DELTA}) WHERE id IN (${ID_LIST});"
    echo "Adjusted predicted_value by ${DELTA} for: ${ID_LIST}"
    ;;

  error)
    shift 2
    ID_LIST="$(normalize_id_list "$@")"
    sql "UPDATE cases SET status='error', stage='errored', retry_count = COALESCE(retry_count,0) + 1 WHERE id IN (${ID_LIST});"
    echo "Marked error: ${ID_LIST}"
    ;;

  migrate)
    ensure_cases_column "method" "TEXT"
    ensure_cases_column "url" "TEXT"
    ensure_cases_column "url_path" "TEXT"
    ensure_cases_column "source" "TEXT"
    ensure_cases_column "query_params" "TEXT"
    ensure_cases_column "body_params" "TEXT"
    ensure_cases_column "assigned_agent" "TEXT"
    ensure_cases_column "consumed_at" "TEXT"
    sql "ALTER TABLE cases ADD COLUMN retry_count INTEGER DEFAULT 0;" 2>/dev/null || true
    ;;

  retry-errors)
    MAX_RETRIES="${3:-2}"
    if ! [[ "$MAX_RETRIES" =~ ^[0-9]+$ ]]; then
      echo "ERROR: max_retries must be a positive integer" >&2
      exit 1
    fi
    BEFORE=$(sql "SELECT COUNT(*) FROM cases WHERE status='error' AND COALESCE(retry_count,0) < ${MAX_RETRIES};")
    # Reset stage to ingested when retrying error cases — they need to
    # re-enter the active pipeline, not stay at 'errored' (which is
    # outside the legacy fetch's stage filter).
    sql "UPDATE cases SET status='pending', stage='ingested', assigned_agent=NULL, consumed_at=NULL WHERE status='error' AND COALESCE(retry_count,0) < ${MAX_RETRIES};"
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
    shift 2

    requeued_existing=0
    if (($# > 0)); then
      REQUEUE_ID_ARGS=()
      for token in "$@"; do
        token="${token// /}"
        token="${token#,}"
        token="${token%,}"
        [[ -z "$token" ]] && continue
        if [[ "$token" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
          REQUEUE_ID_ARGS+=("$token")
          continue
        fi
        break
      done

      if ((${#REQUEUE_ID_ARGS[@]} > 0)); then
        ID_LIST="$(normalize_id_list "${REQUEUE_ID_ARGS[@]}")"
        # Stage handling: if the case is at a TERMINAL stage
        # (clean / exploited / api_tested / errored) then requeue treats
        # it as fresh work and resets stage to ingested. If the case is
        # at an ACTIVE stage (ingested / source_analyzed / vuln_confirmed)
        # we preserve the stage so the next subagent picks it up at the
        # right point in the pipeline (e.g. a vuln_confirmed case
        # requeued by exploit-developer should stay at vuln_confirmed).
        sql "UPDATE cases SET
                status='pending',
                stage = CASE WHEN stage IN ('clean','exploited','api_tested','errored')
                             THEN 'ingested' ELSE stage END,
                assigned_agent=NULL,
                consumed_at=NULL
              WHERE id IN (${ID_LIST});"
        echo "Requeued existing: ${ID_LIST}"
        requeued_existing=1
      fi
    fi

    if [[ "$requeued_existing" == "1" ]]; then
      :
    else
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
    fi
    ;;

  *)
    echo "Unknown action: ${ACTION}"
    echo "Usage: $0 <db_path> {stats|fetch|done|error|reset-stale|retry-errors|migrate|requeue}"
    exit 1
    ;;
esac
