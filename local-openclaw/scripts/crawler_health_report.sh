#!/usr/bin/env bash
set -euo pipefail

run_id="${1:?usage: crawler_health_report.sh <run_id> [label]}"
label="${2:-Run}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/orchestrator_auth.sh"

ORCH_BASE_URL="${ORCH_BASE_URL:-http://127.0.0.1:18000}"
ORCH_TOKEN="${ORCH_TOKEN:-}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"

ensure_orchestrator_token

snapshot_json="$(python3 "$ROOT_DIR/scripts/run_context_snapshot.py" "$run_id")"
summary_json="$(printf '%s' "$snapshot_json" | jq '.summary')"
observed_json="$(printf '%s' "$snapshot_json" | jq '.observed_paths')"
artifact_json="$(printf '%s' "$snapshot_json" | jq '.artifact')"

run_target="$(printf '%s' "$summary_json" | jq -r '.target.target // empty')"
run_status="$(printf '%s' "$summary_json" | jq -r '.target.status // empty')"
engagement_dir="$(printf '%s' "$summary_json" | jq -r '.target.engagement_dir // empty')"
current_phase="$(printf '%s' "$summary_json" | jq -r '.current.phase // empty')"
current_task="$(printf '%s' "$summary_json" | jq -r '.current.task_name // empty')"
total_cases="$(printf '%s' "$summary_json" | jq -r '.coverage.total_cases // 0')"
total_surfaces="$(printf '%s' "$summary_json" | jq -r '.coverage.total_surfaces // 0')"
observed_total="$(printf '%s' "$observed_json" | jq 'length')"
direct_crawler_observed="$(printf '%s' "$observed_json" | jq '[.[] | select((.source // "") | test("^katana"))] | length')"
# Source-analyzer entries are commonly second-order expansions from crawler-discovered
# pages/assets (for example JS bundle route/API extraction on SPA targets). Counting all
# of them as "non-crawler" produces false positives on healthy runs like OKX.
crawler_assisted_observed="$(printf '%s' "$observed_json" | jq '[.[] | select(((.source // "") | test("^katana")) or (.source // "" ) == "source-analyzer")] | length')"
non_crawler_observed=$(( observed_total - crawler_assisted_observed ))
crawler_candidate_total="$(printf '%s' "$observed_json" | jq '[.[] | select(((.type // "unknown") | IN("api", "javascript", "page", "stylesheet", "websocket")))] | length')"
crawler_seed_candidate_total="$(printf '%s' "$observed_json" | jq '[.[] | select(((.type // "unknown") | IN("api", "javascript", "page", "stylesheet", "websocket")) and (((.source // "") | IN("requeue", "vulnerability-analyst", "operator")) | not))] | length')"
crawler_seed_candidate_direct_observed="$(printf '%s' "$observed_json" | jq '[.[] | select(((.type // "unknown") | IN("api", "javascript", "page", "stylesheet", "websocket")) and (((.source // "") | IN("requeue", "vulnerability-analyst", "operator")) | not) and ((.source // "") | test("^katana")))] | length')"
crawler_seed_candidate_effective_observed="$(printf '%s' "$observed_json" | jq '[.[] | select(((.type // "unknown") | IN("api", "javascript", "page", "stylesheet", "websocket")) and ((((.source // "") | test("^katana")) or (.source // "") == "source-analyzer")))] | length')"
supplemental_non_crawler_observed=$(( observed_total - crawler_seed_candidate_total ))

katana_output_lines="$(printf '%s' "$artifact_json" | jq -r '.files.katana_output_lines // 0')"
surfaces_lines="$(printf '%s' "$artifact_json" | jq -r '.files.surfaces_lines // 0')"
katana_error_tail="$(printf '%s' "$artifact_json" | jq -r '.files.katana_error_tail // empty')"
cases_source_counts="$(printf '%s' "$artifact_json" | jq -r '(.cases.source_counts // []) | if length == 0 then "(cases.db unavailable)" else map("\(.source) \(.count)") | join("\n") end')"

observed_type_counts="$(printf '%s' "$observed_json" | jq -r 'group_by(.type // "unknown") | map("- \((.[0].type // "unknown")): \(length)") | .[]?' 2>/dev/null || true)"
observed_source_counts="$(printf '%s' "$observed_json" | jq -r 'group_by(.source // "unknown") | map("- \((.[0].source // "unknown")): \(length)") | .[]?' 2>/dev/null || true)"
fallback_applied="$(printf '%s' "$artifact_json" | jq -r '.integrity.fallback_applied // false')"
fallback_reasons="$(printf '%s' "$artifact_json" | jq -r '(.integrity.reasons // []) | map("- " + .) | .[]?')"

printf '## %s Crawler Health\n\n' "$label"
printf -- '- run_id: %s\n' "$run_id"
printf -- '- target: %s\n' "$run_target"
printf -- '- run_status: %s\n' "$run_status"
printf -- '- current_phase: %s\n' "$current_phase"
printf -- '- current_task: %s\n' "$current_task"
printf -- '- total_cases: %s\n' "$total_cases"
printf -- '- total_surfaces: %s\n' "$total_surfaces"
printf -- '- observed_paths_total: %s\n' "$observed_total"
printf -- '- direct_crawler_observed_paths: %s\n' "$direct_crawler_observed"
printf -- '- crawler_assisted_observed_paths: %s\n' "$crawler_assisted_observed"
printf -- '- non_crawler_observed_paths: %s\n' "$non_crawler_observed"
printf -- '- crawler_candidate_total: %s\n' "$crawler_candidate_total"
printf -- '- crawler_seed_candidate_total: %s\n' "$crawler_seed_candidate_total"
printf -- '- crawler_seed_candidate_direct_observed_paths: %s\n' "$crawler_seed_candidate_direct_observed"
printf -- '- crawler_seed_candidate_effective_observed_paths: %s\n' "$crawler_seed_candidate_effective_observed"
printf -- '- supplemental_non_crawler_observed_paths: %s\n' "$supplemental_non_crawler_observed"
printf -- '- katana_output_lines: %s\n' "$katana_output_lines"
printf -- '- surfaces_lines: %s\n' "$surfaces_lines"
printf -- '\n### Observed path types\n\n'
if [[ -n "$observed_type_counts" ]]; then
  printf '%s\n' "$observed_type_counts"
else
  printf '%s\n' '- (none)'
fi
printf -- '\n### Observed path sources\n\n'
if [[ -n "$observed_source_counts" ]]; then
  printf '%s\n' "$observed_source_counts"
else
  printf '%s\n' '- (none)'
fi
printf -- '\n### cases.db source counts\n\n'
printf '```text\n%s\n```\n' "$cases_source_counts"

printf -- '\n### Summary integrity\n\n'
printf -- '- artifact_fallback_applied: %s\n' "$fallback_applied"
if [[ -n "$fallback_reasons" ]]; then
  printf '%s\n' "$fallback_reasons"
else
  printf '%s\n' '- no API/artifact mismatch detected'
fi

alerts=()
if (( total_cases >= 10 && observed_total < 5 )); then
  alerts+=("Observed path types are too sparse relative to cases.db; investigate crawler ingestion / observed-path generation bugs.")
fi
if (( crawler_seed_candidate_total > 0 && crawler_seed_candidate_effective_observed * 2 < crawler_seed_candidate_total )); then
  alerts+=("Most primary crawler-eligible discoveries are not crawler-assisted; investigate crawler coverage and Katana/source-analysis ingestion bugs.")
fi
if (( katana_output_lines > 0 && crawler_seed_candidate_effective_observed == 0 )); then
  alerts+=("Katana output exists but crawler-assisted observed paths are empty; investigate crawler-to-cases / observed-path derivation bugs.")
fi
if (( total_cases > 0 && total_surfaces == 0 )); then
  alerts+=("cases.db has rows but surfaces are empty; investigate crawler/surface tracking drift.")
fi

printf -- '\n### Crawler bug focus signals\n\n'
if (( ${#alerts[@]} > 0 )); then
  for alert in "${alerts[@]}"; do
    printf -- '- ALERT: %s\n' "$alert"
  done
else
  printf '%s\n' '- No immediate crawler coverage alert from the current heuristics.'
fi

if [[ -n "$katana_error_tail" ]]; then
  printf -- '\n### katana_error.log tail\n\n'
  printf '```text\n%s\n```\n' "$katana_error_tail"
fi
