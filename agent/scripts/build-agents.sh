#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCODE_JSON="$AGENT_DIR/.opencode/opencode.json"
TXT_DIR="$AGENT_DIR/.opencode/prompts/agents"
CLAUDE_DIR="$AGENT_DIR/.claude/agents"
CODEX_DIR="$AGENT_DIR/.codex/agents"

$DRY_RUN && echo "[DRY RUN] No files will be written."

# Validate prerequisites
if [ ! -f "$OPENCODE_JSON" ]; then
  echo "ERROR: $OPENCODE_JSON not found" >&2; exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required but not installed" >&2; exit 1
fi

$DRY_RUN || mkdir -p "$CLAUDE_DIR" "$CODEX_DIR"

map_tools() {
  local agent="$1"
  local tools=""
  for perm in read write edit bash glob grep; do
    val=$(jq -r ".agent[\"$agent\"].$perm // false" "$OPENCODE_JSON")
    if [ "$val" = "true" ]; then
      case $perm in
        read) tools="${tools:+$tools, }Read" ;;
        write) tools="${tools:+$tools, }Write" ;;
        edit) tools="${tools:+$tools, }Edit" ;;
        bash) tools="${tools:+$tools, }Bash" ;;
        glob) tools="${tools:+$tools, }Glob" ;;
        grep) tools="${tools:+$tools, }Grep" ;;
      esac
    fi
  done
  echo "$tools"
}

errors=0
count=0
for agent in $(jq -r '.agent | to_entries[] | select(.value.mode == "subagent") | .key' "$OPENCODE_JSON"); do
  txt_file="$TXT_DIR/${agent}.txt"
  if [ ! -f "$txt_file" ]; then
    echo "  ERROR: $txt_file not found" >&2
    errors=$((errors + 1))
    continue
  fi

  desc=$(jq -r ".agent[\"$agent\"].description" "$OPENCODE_JSON")
  tools=$(map_tools "$agent")

  if [ -z "$desc" ] || [ "$desc" = "null" ]; then
    echo "  ERROR: $agent has no description in opencode.json" >&2
    errors=$((errors + 1))
    continue
  fi

  if [ -z "$tools" ]; then
    echo "  WARN: $agent has no tools mapped (no permissions set)" >&2
  fi

  content=$(cat "$txt_file")
  content_lines=$(wc -l < "$txt_file" | tr -d ' ')

  if $DRY_RUN; then
    echo "  [OK] $agent: $txt_file ($content_lines lines) → tools: $tools"
  else
    # Generate Claude Code .md
    cat > "$CLAUDE_DIR/${agent}.md" << MDEOF
---
name: ${agent}
description: ${desc}
tools: ${tools}
---

${content}
MDEOF

    # Generate Codex .toml
    {
      echo "name = \"${agent}\""
      echo "description = \"${desc}\""
      echo ""
      echo "developer_instructions = \"\"\""
      echo "$content"
      echo "\"\"\""
    } > "$CODEX_DIR/${agent}.toml"

    echo "  Built: $agent"
  fi

  count=$((count + 1))
done

# --- Commands: copy from OpenCode to Claude Code ---
OPENCODE_CMDS="$AGENT_DIR/.opencode/commands"
CLAUDE_CMDS="$AGENT_DIR/.claude/commands"
cmd_count=0

if [ -d "$OPENCODE_CMDS" ]; then
  cmd_files=$(ls "$OPENCODE_CMDS"/*.md 2>/dev/null || true)
  if [ -n "$cmd_files" ]; then
    cmd_count=$(echo "$cmd_files" | wc -l | tr -d ' ')
    if $DRY_RUN; then
      echo "  [OK] $cmd_count commands found in .opencode/commands/"
    else
      mkdir -p "$CLAUDE_CMDS"
      cp "$OPENCODE_CMDS"/*.md "$CLAUDE_CMDS/"
      echo "  Copied $cmd_count commands to .claude/commands/"
    fi
  fi
else
  echo "  WARN: $OPENCODE_CMDS not found" >&2
fi

echo ""
if [ $errors -gt 0 ]; then
  echo "FAILED: $errors error(s) found."
  exit 1
fi

if $DRY_RUN; then
  echo "DRY RUN PASSED: $count agents + $cmd_count commands validated."
else
  echo "Done. Generated $count agents + $cmd_count commands."
fi
