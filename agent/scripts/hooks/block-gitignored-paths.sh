#!/usr/bin/env bash
# Block commits that stage files under paths the project keeps gitignored as
# local-only. Catches `git add -f` force-adds (which bypass gitignore) and
# any other route that puts these paths in the index.
#
# Forbidden prefixes (kept in sync with .gitignore policy):
#   tests/                            — local QA test infrastructure
#   local-hermes-agent/               — operator-side audit / cycle tooling
#   agent/tests/                      — legacy colocated tests (consolidated)
#   orchestrator/tests/               — legacy colocated tests
#   orchestrator/backend/tests/       — legacy colocated tests
#   orchestrator/frontend/src/test/   — legacy colocated tests
#   orchestrator/backend/data/        — runtime state (DB, projects)
#
# Why the hook exists: on 2026-05-07 the auditor SKILL contained a rule
# allowing `git add -f tests/...` for "committed regression tests". Across
# 2026-04-29 → 2026-05-06 that rule produced 26 force-added files across
# dev / master / v0.1.0 / v0.1.1 that did not belong on the public release.
# Scrubbing them required `git filter-repo` plus force-pushes for both
# branches and both release tags. This hook is the prevention layer so
# that pattern can't recur silently — if a regression test is genuinely
# needed, keep it on local disk only.

set -euo pipefail

forbidden_re='^(tests/|local-hermes-agent/|agent/tests/|orchestrator/tests/|orchestrator/backend/tests/|orchestrator/frontend/src/test/|orchestrator/backend/data/)'

# --diff-filter=AMR: Added, Modified, Renamed (rename target). Deletions
# (D) are intentionally allowed so this hook never blocks future cleanup
# commits that remove already-tracked files from these paths.
violations=$(git diff --cached --name-only --diff-filter=AMR \
    | grep -E "$forbidden_re" \
    || true)

if [[ -n "$violations" ]]; then
    {
        echo ""
        echo "ERROR: commit stages files under gitignored local-only paths:"
        printf '  %s\n' $violations
        echo ""
        echo "These trees are intentionally kept off git (see .gitignore policy)."
        echo "If a regression test is genuinely needed, keep it on local disk only;"
        echo "do NOT use 'git add -f' to override. Removing these from git history"
        echo "later requires filter-repo + force-push, which is disruptive."
        echo ""
        echo "Unstage with:"
        echo "    git restore --staged <path>"
        echo ""
    } >&2
    exit 1
fi

exit 0
