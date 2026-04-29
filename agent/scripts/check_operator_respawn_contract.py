#!/usr/bin/env python3
"""Regression guard for operator prompt auth-respawn dispatch contract."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "operator-core.md",
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / ".opencode" / "prompts" / "agents" / "operator.txt",
]

REQUIRED = [
    "AUTH_RESPAWN_REQUIRED=1",
    "the very next assistant action(s) MUST be real subagent `task(...)` dispatches",
    "Only after both task calls have actually been issued and returned may you run",
    "Never clear `.auth-respawn-required` before the real task calls",
    "Never put pseudo-dispatch lines such as `task @recon-specialist ...` inside a bash block",
]

FORBIDDEN = [
    'task @recon-specialist "$DIR with auth.json validated_credentials"',
    'task @source-analyzer "$DIR with auth.json validated_credentials"',
]


def main() -> int:
    failures: list[str] = []
    for path in FILES:
        text = path.read_text()
        for needle in REQUIRED:
            if needle not in text:
                failures.append(f"{path.relative_to(ROOT)} missing required contract text: {needle}")
        for needle in FORBIDDEN:
            if needle in text:
                failures.append(f"{path.relative_to(ROOT)} still contains forbidden pseudo-dispatch: {needle}")
    if failures:
        print("operator respawn contract FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("operator respawn contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
