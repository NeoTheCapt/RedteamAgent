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
    'hard pre-report gate, not a hint and not dependent on the latest handoff wording',
    'If ANY peak-solved challenge remains false, CTF recall closure is NOT satisfied',
    'append a `CTF recall gate` log entry naming every false peak challenge',
    'blocked `/ftp` artifact+bypass path for forgotten backup/signature/easter-egg/deprecated-interface challenges',
    '`Missing Encoding`, and `Password Hash Leak`',
    '`Password Hash Leak`: when `/ftp`, backup files, SQL/account dumps, or credential-bearing artifacts are discovered',
    'solved-check `Password Hash Leak` separately from generic `Exposed credentials` / `User Credentials` evidence',
    'Do not transition to `report`, dispatch `report-writer`, or finalize the run until this explicit gate action is visible in `log.md`',
    'Never emit status-only text such as `[operator] Continuing closure batch.` after a non-empty closure fetch',
    'promotion, non-empty `fetch_batch_to_file.sh`, and exploit-developer handoff are inseparable',
    'A closure branch with `BATCH_COUNT>0` sitting in `processing` without the matching exploit-developer task is a queue-stall bug',
    '`Forgotten Developer Backup` (developer backup artifact plus `%2500.md`/blocked-file bypass candidate)',
    '`Five-Star Feedback` (rating=5 feedback via `/api/Feedbacks/` or native feedback route)',
    'signed `/rest/user/authentication-details/` or another hash-bearing consumer over generic `/api/Users` enumeration',
    'A browser message saying MetaMask/provider is missing is NOT terminal',
    'provider-emulated browser flow (workspace-local injected `window.ethereum` stub or existing browser_flow wallet shim)',
    'the next closure action MUST try a second concrete carrier before declaring exhaustion',
    'native login form SQLi branch with a `sqlite_master` UNION payload',
    'both raw and percent-encoded hash-route variants',
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
