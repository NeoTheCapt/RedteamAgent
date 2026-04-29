#!/usr/bin/env python3
"""Static contract checks for rendered operator prompt guardrails.

This intentionally avoids pytest so auditor cycles can run it with the system
Python after prompt regeneration.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "operator-core.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / ".opencode" / "prompts" / "agents" / "operator.txt",
]
REQUIRED_SNIPPETS = [
    '"remained unsolved"',
    '"no multi-step attack path"',
    'credential hashes were exfiltrated but `User Credentials` did not flip',
    'Before dispatching `report-writer` on a local Juice Shop run',
    'treat that handoff as incomplete: reopen or requeue the exact challenge branch',
    'blocked `/ftp` artifact+bypass path for forgotten backup/signature/easter-egg challenges',
]


def main() -> int:
    failures = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for snippet in REQUIRED_SNIPPETS:
            if snippet not in text:
                failures.append(f"{path.relative_to(ROOT)} missing {snippet!r}")
    if failures:
        print("operator prompt contract failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("operator prompt contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
