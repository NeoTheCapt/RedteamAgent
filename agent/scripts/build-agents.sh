#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCODE_JSON="$AGENT_DIR/.opencode/opencode.json"
TXT_DIR="$AGENT_DIR/.opencode/prompts/agents"
CLAUDE_DIR="$AGENT_DIR/.claude/agents"
CODEX_DIR="$AGENT_DIR/.codex/agents"

mkdir -p "$CLAUDE_DIR" "$CODEX_DIR"

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

count=0
for agent in $(jq -r '.agent | to_entries[] | select(.value.mode == "subagent") | .key' "$OPENCODE_JSON"); do
  txt_file="$TXT_DIR/${agent}.txt"
  if [ ! -f "$txt_file" ]; then
    echo "WARN: $txt_file not found, skipping"
    continue
  fi

  desc=$(jq -r ".agent[\"$agent\"].description" "$OPENCODE_JSON")
  tools=$(map_tools "$agent")
  content=$(cat "$txt_file")

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
  # Use printf to handle multiline content safely in TOML
  {
    echo "name = \"${agent}\""
    echo "description = \"${desc}\""
    echo ""
    echo "developer_instructions = \"\"\""
    echo "$content"
    echo "\"\"\""
  } > "$CODEX_DIR/${agent}.toml"

  count=$((count + 1))
  echo "  Built: $agent"
done

echo "Done. Generated $count agents for Claude Code (.md) and Codex (.toml)."
