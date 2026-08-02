#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$ROOT_DIR/agent/scripts"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

assert_shared_mode() {
    local path="$1"
    local parent="$2"
    local mode file_gid parent_gid
    mode="$(stat -c '%a' "$path")"
    file_gid="$(stat -c '%g' "$path")"
    parent_gid="$(stat -c '%g' "$parent")"
    if [[ "$mode" != "664" ]]; then
        echo "FAIL: expected mode 664 for $path, got $mode" >&2
        return 1
    fi
    if [[ "$file_gid" != "$parent_gid" ]]; then
        echo "FAIL: expected $path gid $file_gid to inherit parent gid $parent_gid" >&2
        return 1
    fi
}

# Phase updates replace scope.json atomically; the result must remain readable
# by the host-side orchestrator user.
phase_dir="$TMP_ROOT/phase"
mkdir -p "$phase_dir"
chmod 2775 "$phase_dir"
printf '%s\n' '{"current_phase":"recon","phases_completed":[]}' >"$phase_dir/scope.json"
chmod 0644 "$phase_dir/scope.json"
sqlite3 "$phase_dir/cases.db" <<'SQL'
CREATE TABLE cases (stage TEXT, status TEXT, assigned_agent TEXT);
INSERT INTO cases(stage,status,assigned_agent) VALUES ('ingested','pending','');
SQL
"$SCRIPTS/update_phase_from_stages.sh" "$phase_dir" >/dev/null
assert_shared_mode "$phase_dir/scope.json" "$phase_dir"

# Surface upserts use a temporary JSONL file and atomic replacement.
surface_dir="$TMP_ROOT/surface"
mkdir -p "$surface_dir"
chmod 2775 "$surface_dir"
"$SCRIPTS/append_surface.sh" "$surface_dir" auth_entry 'GET /login' test 'permission regression' '' discovered >/dev/null
assert_shared_mode "$surface_dir/surfaces.jsonl" "$surface_dir"

# Finding-count updates must not make findings unreadable to the UI.
findings_dir="$TMP_ROOT/findings"
mkdir -p "$findings_dir"
chmod 2775 "$findings_dir"
printf '%s\n' '# Findings' '- **Finding Count**: 0' '## [FINDING-VA-001] Example' >"$findings_dir/findings.md"
chmod 0644 "$findings_dir/findings.md"
# shellcheck source=/dev/null
source "$SCRIPTS/lib/findings.sh"
update_finding_count "$findings_dir/findings.md"
assert_shared_mode "$findings_dir/findings.md" "$findings_dir"

# Finalization atomically replaces scope, log, and report; all are UI artifacts.
final_dir="$TMP_ROOT/final"
mkdir -p "$final_dir"
chmod 2775 "$final_dir"
printf '%s\n' '{"target":"https://example.test/","status":"in_progress","current_phase":"report","phases_completed":[],"start_time":"2026-01-01T00:00:00Z"}' >"$final_dir/scope.json"
printf '%s\n' '# Engagement Log' '- **Status**: In Progress' >"$final_dir/log.md"
printf '%s\n' '# Report' '**Date**: 2026-01-01 — In Progress' '**Status**: In Progress' >"$final_dir/report.md"
chmod 0644 "$final_dir/scope.json" "$final_dir/log.md" "$final_dir/report.md"
EMIT_RUNTIME_EVENT=/nonexistent "$SCRIPTS/finalize_engagement.sh" "$final_dir" >/dev/null
assert_shared_mode "$final_dir/scope.json" "$final_dir"
assert_shared_mode "$final_dir/log.md" "$final_dir"
assert_shared_mode "$final_dir/report.md" "$final_dir"

echo 'PASS: public artifact atomic replacements preserve shared mode 0664 and parent group'
