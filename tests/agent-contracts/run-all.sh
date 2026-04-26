#!/usr/bin/env bash
set -uo pipefail  # NOTE: no -e — we want to keep iterating after a single test fails
                  # so the report shows the FULL set of failures, not just the first.

# run-all.sh — Run every executable contract test in this directory and
# emit a pass/fail summary. Exits 0 only when every test passes.
#
# Why this exists: as of 2026-04-26 the project has 8 agent-contract
# tests covering D1/D2/D5 (subagent prompt drift), D6 (exploit CTF
# solved-state), D7 (stage-set drift), browser-flow regressions, and
# pre-enable audit gates. They were all hand-invokable but only ran
# when someone remembered. This runner is the single entrypoint for
# CI / pre-commit / hermes-auditor cycles to invoke "run all contract
# tests" without having to enumerate them.
#
# Conventions:
#   - any executable .sh in this directory is treated as a test;
#   - run-all.sh excludes itself;
#   - test exit 0 = pass, anything else = fail;
#   - per-test stdout is captured but only printed on failure (or
#     with -v to see everything);
#   - final exit code is 0 iff all tests pass.
#
# Usage:
#   bash tests/agent-contracts/run-all.sh           # quiet; only failed-test output
#   bash tests/agent-contracts/run-all.sh -v        # print every test's full output

VERBOSE=0
case "${1:-}" in
    -v|--verbose) VERBOSE=1 ;;
    -h|--help)
        sed -n '/^# /,/^$/p' "$0" | sed 's/^# \?//'
        exit 0
        ;;
esac

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$(basename "$0")"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$ROOT"

# Collect tests deterministically (sorted by name). Use a portable
# loop instead of `mapfile` — macOS still ships bash 3.2 by default
# and `mapfile` is bash 4+.
TESTS=()
while IFS= read -r line; do
    TESTS+=("$line")
done < <(find "$DIR" -maxdepth 1 -type f -name "test_*.sh" -perm +111 | sort)

if [[ ${#TESTS[@]} -eq 0 ]]; then
    echo "no executable test_*.sh files found in $DIR" >&2
    exit 2
fi

passed=0
failed=0
failures=()

printf '%s\n' "running ${#TESTS[@]} contract test(s) from $DIR"
printf '%s\n' "----------------------------------------------------------------"

for test_path in "${TESTS[@]}"; do
    name="$(basename "$test_path")"
    [[ "$name" == "$SELF" ]] && continue

    output_file="$(mktemp "${TMPDIR:-/tmp}/test-$name.XXXXXX.out")"
    if bash "$test_path" >"$output_file" 2>&1; then
        passed=$((passed + 1))
        printf '  ✓ %s\n' "$name"
        if (( VERBOSE )); then
            sed 's/^/      /' "$output_file"
        fi
    else
        rc=$?
        failed=$((failed + 1))
        failures+=("$name (exit=$rc)")
        printf '  ✗ %s  (exit=%d)\n' "$name" "$rc"
        sed 's/^/      /' "$output_file"
    fi
    rm -f "$output_file"
done

printf '%s\n' "----------------------------------------------------------------"
printf 'passed: %d   failed: %d   total: %d\n' "$passed" "$failed" "${#TESTS[@]}"

if (( failed > 0 )); then
    printf '\nfailures:\n'
    printf '  - %s\n' "${failures[@]}"
    exit 1
fi

exit 0
