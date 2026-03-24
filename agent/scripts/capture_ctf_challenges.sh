#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/container.sh"

ENG_DIR="${1:?usage: capture_ctf_challenges.sh <engagement_dir>}"
SCOPE_FILE="$ENG_DIR/scope.json"
RAW_FILE="$ENG_DIR/challenges.json"
SUMMARY_FILE="$ENG_DIR/challenge-summary.md"

[[ -f "$SCOPE_FILE" ]] || { echo "scope.json not found in $ENG_DIR" >&2; exit 1; }

MODE="$(jq -r '.mode // empty' "$SCOPE_FILE" 2>/dev/null || true)"
TARGET="$(jq -r '.target // empty' "$SCOPE_FILE" 2>/dev/null || true)"

if [[ "$MODE" != "ctf" || -z "$TARGET" ]]; then
    exit 0
fi

TARGET="${TARGET%/}"
export ENGAGEMENT_DIR="$ENG_DIR"

tmp_json="$(mktemp "${TMPDIR:-/tmp}/ctf-challenges.XXXXXX")"
cleanup() {
    rm -f "$tmp_json"
}
trap cleanup EXIT

if ! run_tool curl -fsS "${TARGET}/api/Challenges" >"$tmp_json"; then
    exit 0
fi

if ! python3 - <<'PY' "$tmp_json" "$RAW_FILE" "$SUMMARY_FILE"
import json, sys

src, raw_path, summary_path = sys.argv[1:]
with open(src, "r", encoding="utf-8") as fh:
    data = json.load(fh)

if isinstance(data, dict):
    rows = data.get("data") or data.get("challenges") or data.get("items") or []
elif isinstance(data, list):
    rows = data
else:
    rows = []

if not isinstance(rows, list):
    rows = []

solved = []
unsolved = 0
for row in rows:
    if not isinstance(row, dict):
        continue
    name = row.get("name") or row.get("title") or row.get("key") or "unknown"
    solved_flag = row.get("solved")
    if solved_flag is None:
        solved_flag = row.get("status") is True or row.get("status") == "solved"
    if solved_flag:
        solved.append(name)
    else:
        unsolved += 1

with open(raw_path, "w", encoding="utf-8") as out:
    json.dump(rows, out, ensure_ascii=False, indent=2)
    out.write("\n")

with open(summary_path, "w", encoding="utf-8") as out:
    out.write("## CTF Challenge Coverage\n")
    out.write(f"- **Total Challenges**: {len(rows)}\n")
    out.write(f"- **Solved Challenges**: {len(solved)}\n")
    out.write(f"- **Unsolved Challenges**: {unsolved}\n")
    out.write("\n")
    if solved:
        out.write("### Solved Challenges\n")
        for name in solved:
            out.write(f"- {name}\n")
    else:
        out.write("No solved challenges recorded.\n")
PY
then
    exit 0
fi
