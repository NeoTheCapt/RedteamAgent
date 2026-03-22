#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
MODE="${1:-repo}"
OUTPUT_DIR="${2:-$SOURCE_DIR}"

CORE_FILE="$SOURCE_DIR/operator-core.md"
CLAUDE_OUT="$OUTPUT_DIR/CLAUDE.md"
AGENTS_OUT="$OUTPUT_DIR/AGENTS.md"
CLAUDE_WRAPPER_OUT="$OUTPUT_DIR/.claude/agents/operator.md"
CODEX_WRAPPER_OUT="$OUTPUT_DIR/.codex/agents/operator.toml"

render_banner() {
  cat <<'EOF'
```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ██████  ███████ ██████  ████████ ███████  █████  ███    ███║
║   ██   ██ ██      ██   ██    ██    ██      ██   ██ ████  ████║
║   ██████  █████   ██   ██    ██    █████   ███████ ██ ████ ██║
║   ██   ██ ██      ██   ██    ██    ██      ██   ██ ██  ██  ██║
║   ██   ██ ███████ ██████     ██    ███████ ██   ██ ██      ██║
║                                                              ║
║   Autonomous Red Team Simulation Agent                       ║
EOF
}

render_claude() {
  {
    cat <<'EOF'
# RedTeam Agent — Operator Instructions

EOF
    render_banner
    cat <<'EOF'
║   Powered by Claude Code | All targets are CTF/lab envs      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

When a session starts, display the banner above and then:
"[operator] RedTeam Agent ready. Use `/engage <target_url>` to start a new engagement."

---

<!-- Generated from operator-core.md via scripts/render-operator-prompts.sh -->

EOF
    cat "$CORE_FILE"
    cat <<'EOF'

## Claude Dispatch Syntax

Use `@agent-name` when dispatching subagents:
- `@recon-specialist`
- `@source-analyzer`
- `@vulnerability-analyst`
- `@exploit-developer`
- `@fuzzer`
- `@osint-analyst`
- `@report-writer`

## macOS/zsh Compatibility

- Use absolute paths: `/usr/bin/curl`, `/bin/cat`, `/usr/bin/grep`, etc.
- Do NOT use `grep -P` (Perl regex). Use `grep -E` (extended) or `rg` instead.
- HEREDOC: Use unquoted delimiter (`<< EOF`), NOT single-quoted (`<< 'EOF'`).
- New files: use bash commands (mkdir, cat >, echo >). Existing files: use Edit tool.
EOF
  } > "$CLAUDE_OUT"
  perl -0pi -e 's/\n+\z/\n/' "$CLAUDE_OUT"
}

render_agents() {
  {
    cat <<'EOF'
# RedTeam Agent

EOF
    render_banner
    cat <<'EOF'
║   All targets are CTF/lab environments                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

When a session starts, display the banner above and then:
"[operator] RedTeam Agent ready. Use `/engage <target_url>` to start a new engagement."

---

<!-- Generated from operator-core.md via scripts/render-operator-prompts.sh -->

## Agent Roster

| Agent | Role | Dispatched When |
|---|---|---|
| `operator` | Lead red team operator. Drives methodology, coordinates phases, manages state. | Always active. Entry point. |
| `recon-specialist` | Network recon: fingerprinting, directory fuzzing, tech stack, port scanning. | Phase 1. |
| `source-analyzer` | Deep static analysis of HTML/JS/CSS for hidden routes, API endpoints, secrets. | Phase 1 (parallel with recon). |
| `vulnerability-analyst` | Analyzes endpoints, identifies vulnerability patterns, prioritizes attack paths. | Phase 3 consumption loop. |
| `exploit-developer` | Crafts/executes exploits: SQLi, XSS, auth bypass, chain analysis, impact. | Phase 3 (HIGH/MEDIUM) + Phase 4. |
| `fuzzer` | High-volume parameter/directory fuzzing, rapid iteration. | When FUZZER_NEEDED. |
| `osint-analyst` | OSINT intelligence gathering, CVE/breach/DNS/social research. | Phase 4 (parallel with exploit). |
| `report-writer` | Generates structured engagement report from logs and findings. | Phase 5 or on-demand. |

EOF
    cat "$CORE_FILE"
    cat <<'EOF'

## Tool Promotion Workflow

After an engagement, review generated tools in `engagements/<...>/tools/`:
1. Identify reusable tools → create skill in `skills/<name>/SKILL.md`
2. Add path to instructions array in `.opencode/opencode.json`
EOF
  } > "$AGENTS_OUT"
  perl -0pi -e 's/\n+\z/\n/' "$AGENTS_OUT"
}

render_claude_wrapper() {
  mkdir -p "$(dirname "$CLAUDE_WRAPPER_OUT")"
  cat > "$CLAUDE_WRAPPER_OUT" <<'EOF'
---
name: operator
description: Lead red team operator. Drives pentest methodology, coordinates phases, dispatches subagents.
---

You are the lead red team operator.

Load and follow the complete operator instructions from `CLAUDE.md` in the project root.
This wrapper exists only so Claude Code can expose an `operator` agent entrypoint without duplicating prompt text.
EOF
}

render_codex_wrapper() {
  mkdir -p "$(dirname "$CODEX_WRAPPER_OUT")"
  cat > "$CODEX_WRAPPER_OUT" <<'EOF'
name = "operator"
description = "Lead red team operator. Drives pentest methodology, coordinates phases, dispatches subagents. Entry point for all engagements."

developer_instructions = """
Load and follow the complete operator instructions from AGENTS.md in the project root.
This wrapper exists only so Codex can expose an operator entrypoint without duplicating prompt text.
"""
EOF
}

case "$MODE" in
  repo)
    render_claude
    render_agents
    render_claude_wrapper
    render_codex_wrapper
    ;;
  claude-install)
    render_claude
    ;;
  codex-install)
    render_agents
    ;;
  *)
    echo "Usage: $0 [repo|claude-install|codex-install] [output-dir]" >&2
    exit 1
    ;;
esac
