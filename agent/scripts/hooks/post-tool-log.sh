#!/bin/bash
# post-tool-log.sh — Claude Code PostToolUse hook
# Reads hook JSON from stdin, extracts tool info + agent context, appends to engagement log.md
#
# Hook JSON fields used:
#   tool_name        — Bash, Write, Edit, Agent, etc.
#   tool_input       — command (Bash), file_path (Write/Edit), prompt+subagent_type (Agent)
#   tool_response    — stdout/stderr (Bash), success (Write/Edit)
#   agent_type       — which subagent is running (only present in subagent context)
#   hook_event_name  — PostToolUse

# No set -e: jq/grep returning empty is expected, not an error.

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/engagement.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/scope.sh"

# Parse fields
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)
[ -z "$TOOL_NAME" ] && exit 0

AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "operator"' 2>/dev/null || echo "operator")

# Find active engagement directory
ENG_DIR=$(resolve_engagement_dir "$(pwd)" || true)
[ -z "$ENG_DIR" ] && exit 0
[ ! -f "$ENG_DIR/log.md" ] && exit 0

repair_continuous_target_completion() {
  continuous_target_matches "$ENG_DIR" || return 0

  local status current_phase target summary
  status=$(jq -r '.status // empty' "$ENG_DIR/scope.json" 2>/dev/null || true)
  current_phase=$(jq -r '.current_phase // empty' "$ENG_DIR/scope.json" 2>/dev/null || true)
  if [[ "$status" != "complete" && "$current_phase" != "complete" ]]; then
    return 0
  fi

  target=$(scope_target_url "$ENG_DIR")
  jq '
    .status = "in_progress"
    | .current_phase = "report"
    | del(.end_time)
  ' "$ENG_DIR/scope.json" > "$ENG_DIR/.scope.guard.tmp"
  mv "$ENG_DIR/.scope.guard.tmp" "$ENG_DIR/scope.json"

  summary="continuous_target_guard reopened report phase for ${target:-unknown target}"
  if ! tail -n 40 "$ENG_DIR/log.md" 2>/dev/null | grep -Fq "$summary"; then
    {
      printf '\n## [%s] runtime-guard — Scope Guard\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf '**Summary**: %s\n' "$summary"
    } >> "$ENG_DIR/log.md"
  fi
}

repair_continuous_target_completion

# Check scope.json status
STATUS=$(jq -r '.status // "unknown"' "$ENG_DIR/scope.json" 2>/dev/null || echo "unknown")
[ "$STATUS" != "in_progress" ] && exit 0

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# --- Deduplication ---
# Use a stamp file to track last logged command (within this engagement).
# Skip if the same command was logged within the last 3 seconds.
DEDUP_FILE="$ENG_DIR/.last_hook_log"

case "$TOOL_NAME" in
  Bash)
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
    [ -z "$COMMAND" ] && exit 0

    # Skip noise: pure file reads, git ops, test commands
    case "$COMMAND" in
      cat\ *|ls\ *|git\ *|echo\ *|test\ *|"["*|pwd*) exit 0 ;;
    esac

    # Dedup check: compare first 200 chars + timestamp within 3s window
    CMD_KEY=$(echo "$COMMAND" | head -c 200)
    if [ -f "$DEDUP_FILE" ]; then
      LAST_KEY=$(head -1 "$DEDUP_FILE" 2>/dev/null || true)
      LAST_TS=$(tail -1 "$DEDUP_FILE" 2>/dev/null || echo "0")
      NOW_TS=$(date +%s)
      if [ "$CMD_KEY" = "$LAST_KEY" ] && [ -n "$LAST_TS" ] && [ $((NOW_TS - LAST_TS)) -lt 3 ]; then
        exit 0
      fi
    fi
    printf '%s\n%s\n' "$CMD_KEY" "$(date +%s)" > "$DEDUP_FILE"

    # Extract output summary (first 300 chars of stdout)
    OUTPUT_SUMMARY=$(echo "$INPUT" | jq -r '.tool_response.stdout // empty' 2>/dev/null | head -c 300 || true)
    EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exitCode // empty' 2>/dev/null || true)

    # Truncate command for log
    SHORT_CMD=$(echo "$COMMAND" | head -c 200)

    {
      printf '\n## [%s] %s — Bash\n' "$TIMESTAMP" "$AGENT_TYPE"
      printf '**Command**: `%s`\n' "$SHORT_CMD"
      [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ] && printf '**Exit code**: %s\n' "$EXIT_CODE"
      if [ -n "$OUTPUT_SUMMARY" ]; then
        printf '**Output**: %s\n' "$OUTPUT_SUMMARY"
      fi
      if command_hits_in_scope_target_with_raw_curl "$ENG_DIR" "$COMMAND"; then
        printf '**Warning**: In-scope raw curl bypassed `run_tool curl`; switch to `run_tool curl`/`rtcurl`.\n'
      fi
      if printf '%s' "$COMMAND" | rg -q '(^|[;&|(<[:space:]])(run_tool[[:space:]]+)?katana([[:space:]]|$)' && \
         [[ "$COMMAND" != *"start_katana"* ]] && \
         [[ "$COMMAND" != *"katana_ingest.sh"* ]] && \
         [[ "$COMMAND" != *"command -v katana"* ]] && \
         [[ "$COMMAND" != *"katana -version"* ]]; then
        printf '**Warning**: Raw katana launch bypassed `start_katana`/`katana_ingest.sh`; use the supported wrappers only.\n'
      fi
    } >> "$ENG_DIR/log.md"
    ;;

  Agent)
    # Log subagent dispatch — critical for debugging
    SUBAGENT=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // .tool_input.description // empty' 2>/dev/null || true)
    DESCRIPTION=$(echo "$INPUT" | jq -r '.tool_input.description // empty' 2>/dev/null || true)
    PROMPT_PREVIEW=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null | head -c 150 || true)

    {
      printf '\n## [%s] %s — Dispatch Agent\n' "$TIMESTAMP" "$AGENT_TYPE"
      [ -n "$SUBAGENT" ] && printf '**Subagent**: %s\n' "$SUBAGENT"
      [ -n "$DESCRIPTION" ] && printf '**Task**: %s\n' "$DESCRIPTION"
      [ -n "$PROMPT_PREVIEW" ] && printf '**Prompt preview**: %s...\n' "$PROMPT_PREVIEW"
    } >> "$ENG_DIR/log.md"
    ;;

  Write|Edit)
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
    [ -z "$FILE_PATH" ] && exit 0

    # Only log engagement-related file writes (skip tmp, etc.)
    case "$FILE_PATH" in
      *engagements/*|*findings.md|*scope.json|*auth.json)
        SHORT_PATH=$(echo "$FILE_PATH" | sed 's|.*/engagements/|engagements/|')
        printf '\n## [%s] %s — %s\n**File**: `%s`\n' "$TIMESTAMP" "$AGENT_TYPE" "$TOOL_NAME" "$SHORT_PATH" >> "$ENG_DIR/log.md"
        ;;
    esac
    ;;

  *)
    # Skip Read, Glob, Grep, WebFetch — too noisy for engagement log
    exit 0
    ;;
esac

exit 0
