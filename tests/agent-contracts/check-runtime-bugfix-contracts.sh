#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"

EXPLOIT_CMD=agent/.opencode/commands/exploit.md
for file in \
  agent/.opencode/commands/recon.md \
  agent/.opencode/commands/enumerate.md \
  agent/.opencode/commands/scan.md \
  agent/.opencode/commands/vuln-analyze.md \
  agent/.opencode/commands/pivot.md \
  "$EXPLOIT_CMD"
do
  grep -q 'AUTO-CONFIRM / AUTONOMOUS' "$file"
done

grep -q 'present the exploit plan and wait for approval' "$EXPLOIT_CMD"
grep -q 'announce the exploit plan, then proceed without waiting' "$EXPLOIT_CMD"

grep -q 'full findings review for multi-step attack paths / combined impact' agent/.opencode/prompts/agents/operator.txt
grep -q 'No multi-step attack paths identified\.' agent/.opencode/prompts/agents/exploit-developer.txt
grep -q 'No multi-step attack paths identified\.' agent/.opencode/prompts/agents/report-writer.txt
grep -q 'No multi-step attack paths identified\.' agent/.opencode/commands/report.md

echo '[OK] runtime bugfix prompt contracts passed'
