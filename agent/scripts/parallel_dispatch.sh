#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/parallel_config.sh"

FETCH_BATCH="$SCRIPT_DIR/fetch_batch_to_file.sh"

usage() {
  cat >&2 <<EOF
Usage: parallel_dispatch.sh <subcommand> <engagement_dir> [args...]

Subcommands:
  fetch <engagement_dir> <slot_spec> [<slot_spec> ...]
    slot_spec format: <type>:<limit>:<agent>
    e.g.: "api:5:vulnerability-analyst" "javascript:3:source-analyzer"

  record <engagement_dir> ...
    (not yet implemented)
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

      BATCH_ID="batch-${ROUND_TS}-${SLOT_INDEX}"
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
    echo "ERROR: record not yet implemented" >&2
    exit 1
    ;;

  *)
    echo "ERROR: unknown subcommand '$SUBCMD'" >&2
    usage
    ;;
esac
