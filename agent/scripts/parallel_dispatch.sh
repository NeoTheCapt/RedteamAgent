#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/parallel_config.sh"

FETCH_BATCH="$SCRIPT_DIR/fetch_batch_to_file.sh"
EMIT_RUNTIME_EVENT="${EMIT_RUNTIME_EVENT:-$SCRIPT_DIR/emit_runtime_event.sh}"

usage() {
  cat >&2 <<EOF
Usage: parallel_dispatch.sh <subcommand> <engagement_dir> [args...]

Subcommands:
  fetch <engagement_dir> <slot_spec> [<slot_spec> ...]
    slot_spec format: <type>:<limit>:<agent>
    e.g.: "api:5:vulnerability-analyst" "javascript:3:source-analyzer"

  record <engagement_dir>
    Record outcomes from parallel dispatch slots back into the queue.
EOF
  exit 1
}

SUBCMD="${1:-}"
[[ -z "$SUBCMD" ]] && usage
shift

case "$SUBCMD" in
  fetch)
    DIR="${1:?Missing engagement_dir}"
    shift

    if [[ $# -eq 0 ]]; then
      echo "ERROR: at least one slot_spec required" >&2
      exit 1
    fi

    DB_PATH="$DIR/cases.db"
    if [[ ! -f "$DB_PATH" ]]; then
      echo "ERROR: cases.db not found at $DB_PATH" >&2
      exit 1
    fi

    TOTAL_SLOTS=$#

    # Validate: total slots <= REDTEAM_MAX_PARALLEL_BATCHES
    if (( TOTAL_SLOTS > REDTEAM_MAX_PARALLEL_BATCHES )); then
      echo "ERROR: $TOTAL_SLOTS slots requested exceeds REDTEAM_MAX_PARALLEL_BATCHES=$REDTEAM_MAX_PARALLEL_BATCHES" >&2
      exit 1
    fi

    # Validate slot_spec formats and count per-agent-type
    AGENT_LIST=""
    for spec in "$@"; do
      IFS=':' read -r _type _limit agent <<< "$spec"
      if [[ -z "$_type" || -z "$_limit" || -z "$agent" ]]; then
        echo "ERROR: invalid slot_spec '$spec' — expected <type>:<limit>:<agent>" >&2
        exit 1
      fi
      AGENT_LIST="${AGENT_LIST}${agent}"$'\n'
    done

    # Check per-agent count <= REDTEAM_MAX_SAME_AGENT using sort+uniq
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      count="${line%% *}"
      agent="${line#* }"
      if (( count > REDTEAM_MAX_SAME_AGENT )); then
        echo "ERROR: agent '$agent' appears $count times, exceeds REDTEAM_MAX_SAME_AGENT=$REDTEAM_MAX_SAME_AGENT" >&2
        exit 1
      fi
    done <<< "$(printf '%s' "$AGENT_LIST" | sort | uniq -c | sed 's/^ *//')"

    ROUND_TS="$(date +%s)"
    BATCH_DIR="$DIR/batches"
    mkdir -p "$BATCH_DIR"

    # Build slots JSON array
    SLOTS_JSON="[]"
    TOTAL_CASES=0
    SLOT_INDEX=0

    for spec in "$@"; do
      IFS=':' read -r batch_type batch_limit agent <<< "$spec"

      BATCH_ID="batch-${ROUND_TS}-$$-${SLOT_INDEX}-${RANDOM}"
      BATCH_FILE="$BATCH_DIR/${BATCH_ID}.json"
      LOG_FILE="$BATCH_DIR/${BATCH_ID}.log"
      OUTCOMES_FILE="$BATCH_DIR/${BATCH_ID}.outcomes.md"
      AGENT_TAG="${agent}:s${SLOT_INDEX}"

      # Create the log file
      : > "$LOG_FILE"

      # Call fetch_batch_to_file.sh with unique agent tag
      SUMMARY_FILE="$(mktemp "${TMPDIR:-/tmp}/parallel-fetch-summary.XXXXXX")"
      "$FETCH_BATCH" "$DB_PATH" "$batch_type" "$batch_limit" "$AGENT_TAG" "$BATCH_FILE" > "$SUMMARY_FILE" 2>/dev/null || true

      # Parse BATCH_COUNT and BATCH_IDS from summary
      BATCH_COUNT=0
      BATCH_IDS=""
      if [[ -f "$SUMMARY_FILE" ]]; then
        BATCH_COUNT="$(grep '^BATCH_COUNT=' "$SUMMARY_FILE" | head -1 | cut -d= -f2)" || true
        BATCH_IDS="$(grep '^BATCH_IDS=' "$SUMMARY_FILE" | head -1 | cut -d= -f2)" || true
      fi
      rm -f "$SUMMARY_FILE"

      [[ -z "$BATCH_COUNT" ]] && BATCH_COUNT=0

      if (( BATCH_COUNT == 0 )); then
        STATUS="empty"
      else
        STATUS="fetched"
      fi

      TOTAL_CASES=$(( TOTAL_CASES + BATCH_COUNT ))

      # Emit structured dispatch_start event for this slot (best-effort; async).
      if [[ -f "$EMIT_RUNTIME_EVENT" && "$STATUS" == "fetched" ]]; then
        # Project the cases array from the batch file for orchestrator upsert.
        # Orchestrator uses `path`, agent uses `url_path`, so rename in projection.
        if [[ -f "$BATCH_FILE" ]]; then
          cases_array="$(jq -c '[.[] | {id, method, path: .url_path, type}]' "$BATCH_FILE" 2>/dev/null || echo '[]')"
        else
          cases_array="[]"
        fi
        dispatch_payload="$(jq -cn \
            --arg batch "$BATCH_ID" \
            --arg slot "s${SLOT_INDEX}" \
            --argjson case_count "$BATCH_COUNT" \
            --arg type "$batch_type" \
            --arg agent_name "$agent" \
            --arg agent_tag "$AGENT_TAG" \
            --arg case_ids "$BATCH_IDS" \
            --argjson round "${ORCHESTRATOR_ROUND:-0}" \
            --argjson cases "$cases_array" \
            '{batch:$batch, slot:$slot, case_count:$case_count, type:$type,
              agent:$agent_name, agent_tag:$agent_tag, case_ids:$case_ids,
              round:$round, cases:$cases}')"
        bash "$EMIT_RUNTIME_EVENT" \
            "dispatch.started" \
            "${ORCHESTRATOR_PHASE:-consume}" \
            "$BATCH_ID" \
            "$AGENT_TAG" \
            "${batch_type} batch ${BATCH_ID} (${BATCH_COUNT} cases)" \
            --kind dispatch_start \
            --payload-json "$dispatch_payload" || true
      fi

      # Append slot to JSON array
      SLOTS_JSON="$(jq --arg bid "$BATCH_ID" \
                       --arg bt "$batch_type" \
                       --arg ag "$agent" \
                       --arg at "$AGENT_TAG" \
                       --arg bf "$BATCH_FILE" \
                       --arg lf "$LOG_FILE" \
                       --arg of "$OUTCOMES_FILE" \
                       --arg ci "$BATCH_IDS" \
                       --argjson cnt "$BATCH_COUNT" \
                       --arg st "$STATUS" \
                       '. + [{
                         batch_id: $bid,
                         type: $bt,
                         agent: $ag,
                         agent_tag: $at,
                         batch_file: $bf,
                         log_file: $lf,
                         outcomes_file: $of,
                         case_ids: $ci,
                         count: $cnt,
                         status: $st
                       }]' <<< "$SLOTS_JSON")"

      SLOT_INDEX=$(( SLOT_INDEX + 1 ))
    done

    # Write manifest
    MANIFEST_FILE="$BATCH_DIR/manifest.json"
    jq --arg rid "$ROUND_TS" \
       '{round_id: $rid, slots: .}' <<< "$SLOTS_JSON" > "$MANIFEST_FILE"

    # Print compact summary
    printf 'MANIFEST=%s\n' "$MANIFEST_FILE"
    printf 'SLOT_COUNT=%s\n' "$TOTAL_SLOTS"

    SLOT_INDEX=0
    for spec in "$@"; do
      SLOT_DATA="$(jq -r --argjson idx "$SLOT_INDEX" '.slots[$idx] | "\(.batch_id)|\(.type)|\(.agent)|\(.count) cases|\(.case_ids)|\(.status)"' "$MANIFEST_FILE")"
      printf 'SLOT_%s=%s\n' "$SLOT_INDEX" "$SLOT_DATA"
      SLOT_INDEX=$(( SLOT_INDEX + 1 ))
    done

    printf 'TOTAL_CASES=%s\n' "$TOTAL_CASES"
    ;;

  record)
    DIR="${1:?Missing engagement_dir}"
    shift

    DB="$DIR/cases.db"
    BATCHES_DIR="$DIR/batches"
    MANIFEST="$BATCHES_DIR/manifest.json"
    DISPATCHER="$SCRIPT_DIR/dispatcher.sh"

    if [[ ! -f "$DB" ]]; then
      echo "ERROR: cases.db not found at $DB" >&2
      exit 1
    fi
    if [[ ! -f "$MANIFEST" ]]; then
      echo "ERROR: manifest.json not found at $MANIFEST" >&2
      exit 1
    fi

    SLOT_COUNT="$(jq '.slots | length' "$MANIFEST")"
    RECORDED_SLOTS=0
    TOTAL_DONE=0
    TOTAL_REQUEUE=0
    TOTAL_ERROR=0
    TOTAL_ORPHAN=0

    SLOT_IDX=0
    while [ "$SLOT_IDX" -lt "$SLOT_COUNT" ]; do
      SLOT_STATUS="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].status' "$MANIFEST")"
      if [ "$SLOT_STATUS" != "fetched" ]; then
        SLOT_IDX=$(( SLOT_IDX + 1 ))
        continue
      fi

      OUTCOMES_FILE="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].outcomes_file' "$MANIFEST")"
      LOG_FILE="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].log_file' "$MANIFEST")"
      CASE_IDS_CSV="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].case_ids' "$MANIFEST")"
      BATCH_ID="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].batch_id' "$MANIFEST")"
      BATCH_TYPE="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].type' "$MANIFEST")"
      SLOT_AGENT="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].agent' "$MANIFEST")"
      SLOT_AGENT_TAG="$(jq -r --argjson idx "$SLOT_IDX" '.slots[$idx].agent_tag' "$MANIFEST")"

      # Build list of manifest case IDs
      MANIFEST_IDS=""
      IFS=',' read -r -a MANIFEST_ID_ARR <<< "$CASE_IDS_CSV"

      if [ ! -f "$OUTCOMES_FILE" ]; then
        # Missing outcomes — orphan recovery
        printf '[%s] WARNING: missing outcomes file %s — recovering %s cases to pending\n' "$BATCH_ID" "$OUTCOMES_FILE" "${#MANIFEST_ID_ARR[@]}" >> "$LOG_FILE"
        MISSING_ORPHAN=0
        for oid in "${MANIFEST_ID_ARR[@]}"; do
          oid="$(echo "$oid" | tr -d ' ')"
          [ -z "$oid" ] && continue
          sqlite3 "$DB" ".timeout 5000" "UPDATE cases SET status='pending', assigned_agent=NULL WHERE id=$oid AND status='processing';"
          TOTAL_ORPHAN=$(( TOTAL_ORPHAN + 1 ))
          MISSING_ORPHAN=$(( MISSING_ORPHAN + 1 ))
        done
        if [ -f "$EMIT_RUNTIME_EVENT" ]; then
          dispatch_done_payload="$(jq -cn \
              --arg batch "$BATCH_ID" \
              --arg agent "${SLOT_AGENT:-unknown}" \
              --arg agent_tag "${SLOT_AGENT_TAG:-}" \
              --arg type "${BATCH_TYPE:-}" \
              --argjson case_count 0 \
              --argjson done 0 \
              --argjson requeue 0 \
              --argjson errored 0 \
              --argjson orphan "$MISSING_ORPHAN" \
              --arg state "missing_outcomes" \
              --argjson round "${ORCHESTRATOR_ROUND:-0}" \
              '{batch:$batch, agent:$agent, agent_tag:$agent_tag, type:$type,
                case_count:$case_count, done:$done, requeue:$requeue,
                error:$errored, orphan:$orphan, state:$state, round:$round}')"
          bash "$EMIT_RUNTIME_EVENT" \
              "dispatch.done" \
              "${ORCHESTRATOR_PHASE:-consume}" \
              "$BATCH_ID" \
              "${SLOT_AGENT_TAG:-unknown}" \
              "batch $BATCH_ID orphan recovery ($MISSING_ORPHAN cases to pending)" \
              --kind dispatch_done \
              --payload-json "$dispatch_done_payload" || true
        fi
        RECORDED_SLOTS=$(( RECORDED_SLOTS + 1 ))
        SLOT_IDX=$(( SLOT_IDX + 1 ))
        continue
      fi

      # Parse ### Case Outcomes section
      IN_OUTCOMES=0
      DONE_IDS=""
      REQUEUE_IDS=""
      ERROR_IDS=""
      SEEN_IDS=""
      SLOT_DONE=0
      SLOT_REQUEUE=0
      SLOT_ERROR=0

      while IFS= read -r line; do
        case "$line" in
          "### Case Outcomes"*)
            IN_OUTCOMES=1
            continue
            ;;
        esac
        if [ "$IN_OUTCOMES" -eq 0 ]; then
          continue
        fi
        # Stop at next section header
        case "$line" in
          "### "* | "## "* | "# "*)
            break
            ;;
        esac
        # Parse: DONE|REQUEUE|ERROR <id> — ...
        OUTCOME_TYPE="$(echo "$line" | awk '{print $1}')"
        CASE_ID="$(echo "$line" | awk '{print $2}')"

        # Skip lines that don't start with a valid outcome keyword
        case "$OUTCOME_TYPE" in
          DONE|REQUEUE|ERROR) ;;
          *) continue ;;
        esac
        # Skip non-numeric IDs
        case "$CASE_ID" in
          ''|*[!0-9]*) continue ;;
        esac

        SEEN_IDS="${SEEN_IDS}${CASE_ID},"

        case "$OUTCOME_TYPE" in
          DONE)
            if [ -z "$DONE_IDS" ]; then
              DONE_IDS="$CASE_ID"
            else
              DONE_IDS="${DONE_IDS},${CASE_ID}"
            fi
            SLOT_DONE=$(( SLOT_DONE + 1 ))
            ;;
          REQUEUE)
            if [ -z "$REQUEUE_IDS" ]; then
              REQUEUE_IDS="$CASE_ID"
            else
              REQUEUE_IDS="${REQUEUE_IDS},${CASE_ID}"
            fi
            SLOT_REQUEUE=$(( SLOT_REQUEUE + 1 ))
            ;;
          ERROR)
            if [ -z "$ERROR_IDS" ]; then
              ERROR_IDS="$CASE_ID"
            else
              ERROR_IDS="${ERROR_IDS},${CASE_ID}"
            fi
            SLOT_ERROR=$(( SLOT_ERROR + 1 ))
            ;;
        esac

        # Emit structured case_done event for this outcome (best-effort; async).
        if [ -f "$EMIT_RUNTIME_EVENT" ]; then
          # Extract the tail description after the second em-dash, if present.
          case_summary_detail="${line#* }"                 # strip OUTCOME_TYPE
          case_summary_detail="${case_summary_detail#* }"  # strip CASE_ID
          case_summary_detail="${case_summary_detail# }"
          case_summary_detail="${case_summary_detail#— }"
          case_done_payload="$(jq -cn \
              --argjson case_id "$CASE_ID" \
              --arg outcome "$OUTCOME_TYPE" \
              --arg dispatch "$BATCH_ID" \
              --arg agent "${SLOT_AGENT:-unknown}" \
              --arg agent_tag "${SLOT_AGENT_TAG:-}" \
              --arg type "${BATCH_TYPE:-}" \
              --arg detail "${case_summary_detail:-}" \
              --argjson round "${ORCHESTRATOR_ROUND:-0}" \
              '{case_id:$case_id, outcome:$outcome, dispatch:$dispatch,
                agent:$agent, agent_tag:$agent_tag, type:$type,
                detail:$detail, round:$round}')"
          bash "$EMIT_RUNTIME_EVENT" \
              "case.done" \
              "${ORCHESTRATOR_PHASE:-consume}" \
              "case-$CASE_ID" \
              "${SLOT_AGENT_TAG:-unknown}" \
              "$OUTCOME_TYPE case $CASE_ID (${BATCH_ID})" \
              --kind case_done \
              --payload-json "$case_done_payload" || true
        fi
      done < "$OUTCOMES_FILE"

      # Execute dispatcher commands
      if [ -n "$DONE_IDS" ]; then
        "$DISPATCHER" "$DB" done "$DONE_IDS" >> "$LOG_FILE" 2>&1
      fi
      if [ -n "$ERROR_IDS" ]; then
        "$DISPATCHER" "$DB" error "$ERROR_IDS" >> "$LOG_FILE" 2>&1
      fi
      # Requeue via direct SQL
      if [ -n "$REQUEUE_IDS" ]; then
        IFS=',' read -r -a RQ_ARR <<< "$REQUEUE_IDS"
        for rid in "${RQ_ARR[@]}"; do
          rid="$(echo "$rid" | tr -d ' ')"
          [ -z "$rid" ] && continue
          sqlite3 "$DB" ".timeout 5000" "UPDATE cases SET status='pending', assigned_agent=NULL WHERE id=$rid AND status='processing';"
        done
        printf '[%s] Requeued: %s\n' "$BATCH_ID" "$REQUEUE_IDS" >> "$LOG_FILE"
      fi

      # Orphan detection: manifest IDs not seen in outcomes
      SLOT_ORPHAN=0
      for mid in "${MANIFEST_ID_ARR[@]}"; do
        mid="$(echo "$mid" | tr -d ' ')"
        [ -z "$mid" ] && continue
        case ",$SEEN_IDS" in
          *",$mid,"*) ;;
          *)
            sqlite3 "$DB" ".timeout 5000" "UPDATE cases SET status='pending', assigned_agent=NULL WHERE id=$mid AND status='processing';"
            SLOT_ORPHAN=$(( SLOT_ORPHAN + 1 ))
            printf '[%s] Orphan recovered: case %s\n' "$BATCH_ID" "$mid" >> "$LOG_FILE"
            ;;
        esac
      done

      printf '[%s] Recorded: done=%d requeue=%d error=%d orphan=%d\n' \
        "$BATCH_ID" "$SLOT_DONE" "$SLOT_REQUEUE" "$SLOT_ERROR" "$SLOT_ORPHAN" >> "$LOG_FILE"

      # Emit structured dispatch_done event for this slot (best-effort; async).
      if [ -f "$EMIT_RUNTIME_EVENT" ]; then
        slot_total=$(( SLOT_DONE + SLOT_REQUEUE + SLOT_ERROR ))
        # When orphan cases were detected (outcomes file exists but is missing
        # some case IDs), emit state="missing_outcomes" so the backend counts
        # this slot as a failed dispatch rather than a clean completion.
        if (( SLOT_ORPHAN > 0 )); then
          dispatch_done_state="missing_outcomes"
        else
          dispatch_done_state="done"
        fi
        dispatch_done_payload="$(jq -cn \
            --arg batch "$BATCH_ID" \
            --arg agent "${SLOT_AGENT:-unknown}" \
            --arg agent_tag "${SLOT_AGENT_TAG:-}" \
            --arg type "${BATCH_TYPE:-}" \
            --argjson case_count "$slot_total" \
            --argjson done "$SLOT_DONE" \
            --argjson requeue "$SLOT_REQUEUE" \
            --argjson errored "$SLOT_ERROR" \
            --argjson orphan "$SLOT_ORPHAN" \
            --arg state "$dispatch_done_state" \
            --argjson round "${ORCHESTRATOR_ROUND:-0}" \
            '{batch:$batch, agent:$agent, agent_tag:$agent_tag, type:$type,
              case_count:$case_count, done:$done, requeue:$requeue,
              error:$errored, orphan:$orphan, state:$state, round:$round}')"
        bash "$EMIT_RUNTIME_EVENT" \
            "dispatch.done" \
            "${ORCHESTRATOR_PHASE:-consume}" \
            "$BATCH_ID" \
            "${SLOT_AGENT_TAG:-unknown}" \
            "batch $BATCH_ID recorded (done=$SLOT_DONE requeue=$SLOT_REQUEUE error=$SLOT_ERROR orphan=$SLOT_ORPHAN)" \
            --kind dispatch_done \
            --payload-json "$dispatch_done_payload" || true
      fi

      TOTAL_DONE=$(( TOTAL_DONE + SLOT_DONE ))
      TOTAL_REQUEUE=$(( TOTAL_REQUEUE + SLOT_REQUEUE ))
      TOTAL_ERROR=$(( TOTAL_ERROR + SLOT_ERROR ))
      TOTAL_ORPHAN=$(( TOTAL_ORPHAN + SLOT_ORPHAN ))
      RECORDED_SLOTS=$(( RECORDED_SLOTS + 1 ))

      SLOT_IDX=$(( SLOT_IDX + 1 ))
    done

    # Get remaining stats from DB
    PENDING_REMAINING="$(sqlite3 "$DB" ".timeout 5000" "SELECT COUNT(*) FROM cases WHERE status='pending';")"
    PROCESSING_REMAINING="$(sqlite3 "$DB" ".timeout 5000" "SELECT COUNT(*) FROM cases WHERE status='processing';")"

    printf 'RECORDED_SLOTS=%s\n' "$RECORDED_SLOTS"
    printf 'TOTAL_DONE=%s\n' "$TOTAL_DONE"
    printf 'TOTAL_REQUEUE=%s\n' "$TOTAL_REQUEUE"
    printf 'TOTAL_ERROR=%s\n' "$TOTAL_ERROR"
    printf 'TOTAL_ORPHAN=%s\n' "$TOTAL_ORPHAN"
    printf 'PENDING_REMAINING=%s\n' "$PENDING_REMAINING"
    printf 'PROCESSING_REMAINING=%s\n' "$PROCESSING_REMAINING"
    ;;

  *)
    echo "ERROR: unknown subcommand '$SUBCMD'" >&2
    usage
    ;;
esac
