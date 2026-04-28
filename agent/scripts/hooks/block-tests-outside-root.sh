#!/usr/bin/env bash
# Block commits that stage test files outside the root tests/ directory.
# Project policy (set 2026-04-29): all tests live under root tests/, never
# colocated with product source. The whole tests/ tree is gitignored — but
# someone might still bypass that by adding a new test location like
# `agent/foo_test.py`. This hook catches that at commit time.

set -euo pipefail

# Match common test filename patterns:
#   test_<x>.py    test_<x>.sh    *.test.ts    *.test.tsx    *_test.py
# --diff-filter=AM: only Added (A) or Modified (M) — ignore Deletions, so
# the hook doesn't trip when someone is removing tests from a legacy
# colocated location (cleanup case).
violations=$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)(test_[^/]+\.(py|sh)|[^/]+\.test\.(ts|tsx)|[^/]+_test\.(py|go))$' \
    | grep -vE '^tests/' \
    || true)

if [[ -n "$violations" ]]; then
    echo "ERROR: commit stages test files OUTSIDE root tests/:" >&2
    printf '  %s\n' $violations >&2
    echo "" >&2
    echo "Project policy: all tests live under root tests/." >&2
    echo "Move them (preserving the new location's import shape per the existing" >&2
    echo "vitest.config.ts / pyproject.toml testpaths config) and re-stage." >&2
    exit 1
fi

exit 0
