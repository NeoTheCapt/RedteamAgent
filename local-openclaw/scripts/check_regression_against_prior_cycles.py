#!/usr/bin/env python3
"""Detect silent regressions: lines DELETED by the current cycle's commits
that were ADDED by prior audit commits (fix(audit-*)) within the lookback
window.

Runs after Phase 4. If any regression candidates surface, prints them to
stderr and exits non-zero so the controller can flag the cycle as
`success_with_dirty_artifacts` (the same hook F4 uses).

The classic motivating case is cycle 20260423T134501Z commit 8aed200
"rerender operator prompts": it re-generated agent/.opencode/prompts/*
and silently dropped the `parallel_dispatch.sh fetch` rule that a
prior audit commit had added. Phase 4 diff-only review missed it;
this check catches it by noticing that several lines deleted in the
new commits match lines that a prior audit commit inserted.

Usage: check_regression_against_prior_cycles.py <baseline_sha> [--lookback 30]

Heuristic:
  1. Enumerate the HEAD range: baseline_sha..HEAD
  2. Enumerate prior "audit" commits: 30 commits before baseline whose
     subject starts with `fix(audit`
  3. For every file touched in both windows, collect the set of
     non-trivial lines ADDED by prior commits (length >= 20, not pure
     whitespace, not pure braces).
  4. For each line DELETED in the current range, check if it's in the
     prior-added set for the same file. Any hit is a regression
     candidate — print the file, line text, and the prior commit SHA.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIVIAL_LINE_MIN_LEN = 20  # skip `}`, `import foo`, etc.


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(
            cmd, cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return ""


def commits_in_range(range_spec: str) -> list[tuple[str, str]]:
    out = run(["git", "log", "--format=%H %s", range_spec])
    result = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if sha:
            result.append((sha, subject))
    return result


def prior_audit_commits(baseline_sha: str, lookback: int) -> list[tuple[str, str]]:
    """Audit commits that landed BEFORE the current cycle. Only look at the
    most recent N commits preceding baseline_sha to keep the check cheap."""
    out = run(
        [
            "git",
            "log",
            f"--max-count={lookback}",
            "--format=%H %s",
            f"{baseline_sha}~1" if baseline_sha else "HEAD",
        ]
    )
    result = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if sha and subject.startswith("fix(audit"):
            result.append((sha, subject))
    return result


def is_significant_line(s: str) -> bool:
    stripped = s.strip()
    if len(stripped) < TRIVIAL_LINE_MIN_LEN:
        return False
    if not any(ch.isalnum() for ch in stripped):
        return False
    # Skip common structural noise like pure import/export lines.
    return True


def collect_added_lines_per_commit(sha: str) -> dict[str, set[str]]:
    """Return {file_path: set_of_significant_lines_added_by_sha}."""
    out = run(["git", "show", "--no-color", "--format=", "--unified=0", sha])
    per_file: dict[str, set[str]] = defaultdict(set)
    current_file: str | None = None
    for raw in out.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[len("+++ b/") :]
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("+++"):
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            line_text = raw[1:]
            if current_file and is_significant_line(line_text):
                per_file[current_file].add(line_text.rstrip())
    return per_file


def collect_deleted_lines_in_range(range_spec: str) -> dict[str, set[str]]:
    out = run(["git", "log", "-p", "--no-color", "--format=", "--unified=0", range_spec])
    per_file: dict[str, set[str]] = defaultdict(set)
    current_file: str | None = None
    for raw in out.splitlines():
        if raw.startswith("+++ b/") or raw.startswith("--- a/"):
            if raw.startswith("+++ b/"):
                current_file = raw[len("+++ b/") :]
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            line_text = raw[1:]
            if current_file and is_significant_line(line_text):
                per_file[current_file].add(line_text.rstrip())
    return per_file


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_sha",
                        help="commit that was HEAD at the start of the cycle")
    parser.add_argument("--lookback", type=int, default=30,
                        help="how many commits before baseline to scan for prior audit fixes (default 30)")
    args = parser.parse_args(argv)

    cycle_commits = commits_in_range(f"{args.baseline_sha}..HEAD")
    if not cycle_commits:
        # No new commits — nothing to regress.
        return 0

    prior_commits = prior_audit_commits(args.baseline_sha, args.lookback)
    if not prior_commits:
        return 0

    # Build the "lines prior audit commits added" map.
    prior_added: dict[str, dict[str, str]] = defaultdict(dict)  # file → {line_text: prior_sha}
    for sha, _subject in prior_commits:
        per_file = collect_added_lines_per_commit(sha)
        for fp, lines in per_file.items():
            for line in lines:
                # Keep the most recent prior commit for this line.
                prior_added[fp].setdefault(line, sha)

    # Look at what the current cycle's commits delete.
    current_deleted = collect_deleted_lines_in_range(f"{args.baseline_sha}..HEAD")

    regressions: list[tuple[str, str, str]] = []  # (file, line, prior_sha)
    for fp, lines in current_deleted.items():
        prior_for_file = prior_added.get(fp) or {}
        for line in lines:
            sha = prior_for_file.get(line)
            if sha:
                regressions.append((fp, line, sha))

    if not regressions:
        print("[regression-check] no prior-audit lines removed by this cycle", file=sys.stderr)
        return 0

    # Group by file + prior commit for readability.
    by_prior: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fp, line, sha in regressions:
        by_prior[sha].append((fp, line))

    print(
        f"[regression-check] {len(regressions)} prior-audit line(s) removed by this cycle's diff:",
        file=sys.stderr,
    )
    for sha, entries in by_prior.items():
        # Look up the prior commit subject for context.
        subj = run(["git", "log", "-1", "--format=%s", sha]).strip()
        print(f"\n  prior commit {sha[:7]} — {subj}", file=sys.stderr)
        # Dedup file repeats.
        seen_files: set[str] = set()
        for fp, line in entries:
            if fp not in seen_files:
                print(f"    file: {fp}", file=sys.stderr)
                seen_files.add(fp)
            snippet = (line[:80] + "…") if len(line) > 80 else line
            print(f"      - {snippet}", file=sys.stderr)
    print(
        "\n  ACTION: if the removal is intentional (superseded by a new "
        "finding), justify it in review.md. Otherwise restore via a cleanup "
        "commit and reopen the corresponding finding.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
