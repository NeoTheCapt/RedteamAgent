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

set -euo pipefail

INPUT=$(cat)

# Parse fields
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ -z "$TOOL_NAME" ] && exit 0

AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "operator"' 2>/dev/null)

# Find active engagement directory
ENG_DIR=$(ls -td engagements/*/ 2>/dev/null | head -1 | sed 's|/$||')
[ -z "$ENG_DIR" ] && exit 0
[ ! -f "$ENG_DIR/log.md" ] && exit 0

# Check scope.json status
STATUS=$(jq -r '.status // "unknown"' "$ENG_DIR/scope.json" 2>/dev/null)
[ "$STATUS" != "in_progress" ] && exit 0

TIMESTAMP=$(date +%H:%M:%S)

case "$TOOL_NAME" in
  Bash)
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
    [ -z "$COMMAND" ] && exit 0

    # Skip noise: pure file reads, git ops, test commands
    case "$COMMAND" in
      cat\ *|ls\ *|git\ *|echo\ *|test\ *|"["*|pwd*) exit 0 ;;
    esac

    # Extract output summary (first 300 chars of stdout)
    OUTPUT_SUMMARY=$(echo "$INPUT" | jq -r '.tool_response.stdout // empty' 2>/dev/null | head -c 300)
    EXIT_CODE=$(echo "$INPUT" | jq -r '.tool_response.exitCode // empty' 2>/dev/null)

    # Truncate command for log
    SHORT_CMD=$(echo "$COMMAND" | head -c 200)

    {
      printf '\n## [%s] %s — Bash\n' "$TIMESTAMP" "$AGENT_TYPE"
      printf '**Command**: `%s`\n' "$SHORT_CMD"
      [ -n "$EXIT_CODE" ] && [ "$EXIT_CODE" != "0" ] && printf '**Exit code**: %s\n' "$EXIT_CODE"
      if [ -n "$OUTPUT_SUMMARY" ]; then
        printf '**Output**: %s\n' "$OUTPUT_SUMMARY"
      fi
    } >> "$ENG_DIR/log.md"
    ;;

  Agent)
    # Log subagent dispatch — critical for debugging
    SUBAGENT=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // .tool_input.description // empty' 2>/dev/null)
    DESCRIPTION=$(echo "$INPUT" | jq -r '.tool_input.description // empty' 2>/dev/null)
    PROMPT_PREVIEW=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null | head -c 150)

    {
      printf '\n## [%s] %s — Dispatch Agent\n' "$TIMESTAMP" "$AGENT_TYPE"
      [ -n "$SUBAGENT" ] && printf '**Subagent**: %s\n' "$SUBAGENT"
      [ -n "$DESCRIPTION" ] && printf '**Task**: %s\n' "$DESCRIPTION"
      [ -n "$PROMPT_PREVIEW" ] && printf '**Prompt preview**: %s...\n' "$PROMPT_PREVIEW"
    } >> "$ENG_DIR/log.md"
    ;;

  Write|Edit)
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
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
