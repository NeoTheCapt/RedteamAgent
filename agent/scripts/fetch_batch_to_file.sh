#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCHER="$SCRIPT_DIR/dispatcher.sh"

# Two invocation forms (positional, backward compatible):
#   legacy: fetch_batch_to_file.sh <db> <type> <limit> <agent> <out_file>
#   stage:  fetch_batch_to_file.sh <db> --stage <stage> <type> <limit> <agent> <out_file>
#
# The legacy form keeps working unchanged for existing callers. The stage
# form gates fetch on a specific pipeline stage so multiple subagents can
# work on different stages of the same case-type concurrently.
DB_PATH="${1:?usage: fetch_batch_to_file.sh <db_path> [--stage <stage>] <type> <limit> <agent> <out_file>}"
shift

BATCH_STAGE=""
if [[ "${1:-}" == "--stage" ]]; then
    BATCH_STAGE="${2:?--stage requires a value}"
    shift 2
fi

BATCH_TYPE="${1:?usage: fetch_batch_to_file.sh <db_path> [--stage <stage>] <type> <limit> <agent> <out_file>}"
BATCH_LIMIT="${2:?usage: fetch_batch_to_file.sh <db_path> [--stage <stage>] <type> <limit> <agent> <out_file>}"
BATCH_AGENT="${3:?usage: fetch_batch_to_file.sh <db_path> [--stage <stage>] <type> <limit> <agent> <out_file>}"
OUT_FILE_RAW="${4:?usage: fetch_batch_to_file.sh <db_path> [--stage <stage>] <type> <limit> <agent> <out_file>}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "database not found: $DB_PATH" >&2
    exit 1
fi

if [[ "$OUT_FILE_RAW" = /* ]]; then
    OUT_FILE="$OUT_FILE_RAW"
else
    OUT_FILE="$(pwd)/$OUT_FILE_RAW"
fi

mkdir -p "$(dirname "$OUT_FILE")"
OUT_FILE="$(cd "$(dirname "$OUT_FILE")" && pwd)/$(basename "$OUT_FILE")"

stderr_file="$(mktemp "${TMPDIR:-/tmp}/fetch-batch-stderr.XXXXXX")"
trap 'rm -f "$stderr_file"' EXIT

if [[ -n "$BATCH_STAGE" ]]; then
    "$DISPATCHER" "$DB_PATH" fetch-by-stage "$BATCH_STAGE" "$BATCH_TYPE" "$BATCH_LIMIT" "$BATCH_AGENT" >"$OUT_FILE" 2>"$stderr_file"
else
    "$DISPATCHER" "$DB_PATH" fetch "$BATCH_TYPE" "$BATCH_LIMIT" "$BATCH_AGENT" >"$OUT_FILE" 2>"$stderr_file"
fi

# sqlite3 -json UPDATE ... RETURNING emits an empty file (not "[]") when no rows
# match. Treat that as a valid empty batch so the operator can continue scanning
# batch types without surfacing a spurious helper failure.
if [[ ! -s "$OUT_FILE" ]]; then
    printf '[]\n' >"$OUT_FILE"
fi

if ! jq -e type "$OUT_FILE" >/dev/null 2>&1; then
    echo "dispatcher produced invalid JSON for batch fetch" >&2
    cat "$OUT_FILE" >&2 || true
    exit 1
fi

batch_count="$(jq 'length' "$OUT_FILE")"
if [[ "$batch_count" == "0" ]]; then
    batch_ids=""
    batch_paths=""
else
    batch_ids="$(jq -r 'map(.id | tostring) | join(",")' "$OUT_FILE")"
    batch_paths="$(jq -r 'map(.url_path // .url // "") | join(",")' "$OUT_FILE")"
fi

# Annotate each case with four complementary target-agnostic tag families:
#   * input_shapes      — INPUT SHAPE (url-input, xml-input, template-
#                         renderer, json-writer, image-loader); bound to
#                         required INJECTION probe families.
#   * surface_types     — FUNCTIONAL ROLE (auth_entry, account_recovery,
#                         privileged_write, file_handling, workflow_token,
#                         object_reference); bound to required
#                         WORKFLOW-MUTATION families.
#   * stateful_response — boolean — does this write's response shape
#                         imply a state mutation? When true, vuln-analyst
#                         adds read-back / accumulation / cross-session
#                         sub-probes that A's serial mutations don't
#                         reach.
#   * security_context  — {identifier, question, confidence} — when a
#                         password-recovery case exposes a security-
#                         question shape, vuln-analyst writes the pair
#                         into intel.md so the existing intel_changed
#                         hook auto-dispatches osint-analyst to research
#                         candidate answers.
# Each classifier is independent and additive; missing python3 / parse
# error / unrecognized payload leaves the batch untouched.
BATCH_INPUT_SHAPES=""
BATCH_SURFACE_TYPES=""
BATCH_STATEFUL=""
BATCH_SECURITY_CONTEXT=""
if [[ "$batch_count" != "0" ]] && command -v python3 >/dev/null 2>&1; then
    # Single-process driver runs all 4 classifiers in one interpreter
    # cold-start. Pre-H4 fix this was 4 separate python3 invocations
    # (~57 ms / 73 % overhead per batch); collapsing them shaved ~57 ms
    # off every fetch. The driver writes one summary line per classifier
    # to stdout so the grep below still finds each prefix.
    if classify_out="$(python3 "$SCRIPT_DIR/lib/classify_batch.py" "$OUT_FILE" 2>/dev/null)"; then
        while IFS= read -r line; do
            case "$line" in
                input_shapes_summary=*) BATCH_INPUT_SHAPES="${line#input_shapes_summary=}" ;;
                surface_types_summary=*) BATCH_SURFACE_TYPES="${line#surface_types_summary=}" ;;
                stateful_summary=*) BATCH_STATEFUL="${line#stateful_summary=}" ;;
                security_context_summary=*) BATCH_SECURITY_CONTEXT="${line#security_context_summary=}" ;;
            esac
        done <<< "$classify_out"
    fi
fi

printf 'BATCH_FILE=%s\n' "$OUT_FILE"
printf 'BATCH_TYPE=%s\n' "$BATCH_TYPE"
printf 'BATCH_AGENT=%s\n' "$BATCH_AGENT"
printf 'BATCH_STAGE=%s\n' "$BATCH_STAGE"
printf 'BATCH_COUNT=%s\n' "$batch_count"
printf 'BATCH_IDS=%s\n' "$batch_ids"
printf 'BATCH_PATHS=%s\n' "$batch_paths"
if [[ -n "$BATCH_INPUT_SHAPES" ]]; then
    printf 'BATCH_INPUT_SHAPES=%s\n' "$BATCH_INPUT_SHAPES"
fi
if [[ -n "$BATCH_SURFACE_TYPES" ]]; then
    printf 'BATCH_SURFACE_TYPES=%s\n' "$BATCH_SURFACE_TYPES"
fi
if [[ -n "$BATCH_STATEFUL" ]]; then
    printf 'BATCH_STATEFUL=%s\n' "$BATCH_STATEFUL"
fi
if [[ -n "$BATCH_SECURITY_CONTEXT" ]]; then
    printf 'BATCH_SECURITY_CONTEXT=%s\n' "$BATCH_SECURITY_CONTEXT"
fi

if [[ -s "$stderr_file" ]]; then
    printf 'BATCH_NOTE=%s\n' "$(tr '\n' ' ' < "$stderr_file" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
fi

# Emit a structured `dispatch_start` event so the orchestrator-side cases /
# dispatches mirror tables stay populated under SERIALIZED dispatch.
# Best-effort: emit_runtime_event.sh self-noops when ORCHESTRATOR_* env vars
# are unset, and the underlying curl is already backgrounded with 1s/2s
# timeouts.
EMIT_RUNTIME_EVENT="${EMIT_RUNTIME_EVENT:-$SCRIPT_DIR/emit_runtime_event.sh}"
if [[ "$batch_count" -gt 0 && -x "$EMIT_RUNTIME_EVENT" ]] && command -v jq >/dev/null 2>&1; then
    # Synthesize a unique-enough batch id for orchestrator-side dispatches mirror
    # (event_apply.py:_apply_dispatch_start drops payloads with no `batch`).
    batch_id="serial-$(date +%s)-${batch_ids%%,*}"
    cases_array="$(jq -c '[.[] | {id, method, path: .url_path, type}]' "$OUT_FILE" 2>/dev/null || echo '[]')"
    dispatch_payload="$(jq -cn \
        --arg batch "$batch_id" \
        --arg slot "serialized" \
        --argjson case_count "$batch_count" \
        --arg type "$BATCH_TYPE" \
        --arg stage "$BATCH_STAGE" \
        --arg agent_name "$BATCH_AGENT" \
        --arg case_ids "$batch_ids" \
        --argjson cases "$cases_array" \
        '{batch:$batch, slot:$slot, case_count:$case_count, type:$type, stage:$stage,
          agent:$agent_name, case_ids:$case_ids, cases:$cases,
          source:"fetch_batch_to_file.sh"}')"
    bash "$EMIT_RUNTIME_EVENT" \
        "dispatch.started" \
        "${ORCHESTRATOR_PHASE:-consume}" \
        "$batch_id" \
        "$BATCH_AGENT" \
        "${BATCH_TYPE} batch (${batch_count} cases)" \
        --kind dispatch_start \
        --payload-json "$dispatch_payload" 2>/dev/null || true
fi
