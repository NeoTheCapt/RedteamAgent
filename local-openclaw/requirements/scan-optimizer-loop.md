# Scan Optimizer Loop

## Purpose

Provide a local-only automation contract for OpenClaw to continuously improve RedteamOpencode scan quality.

This loop is not a scheduler. OpenClaw or another local runner calls it on a fixed cadence.

## Fixed Targets

Each optimization cycle manages exactly two fixed targets:

1. `https://www.okx.com`
2. `http://127.0.0.1:8000`

For each target, keep at most one active run.

- If the latest run is `queued` or `running`, treat that as the normal in-flight run and continue observing it.
- If the latest run is terminal or abnormal, delete the stale run (and its runtime/container) before creating one fresh replacement run.
- If multiple active runs already exist for the same target, keep only the newest active run and delete the older extra runs.

## Required Behavior Per Cycle

1. Ensure the orchestrator GUI/API is reachable.
2. Before creating or deleting anything, inspect the latest fixed-target runs and their logs/artifacts first.
3. If the current fixed-target runs are healthy and no confirmed bug is found, skip the cycle and let them continue running.
4. If a run is terminal, abnormal, duplicated, or has been running longer than 15 minutes with confirmed buggy behavior, fix the repo bug first, then stop/delete the stale run and its runtime/container, and create exactly one fresh replacement run per affected target for verification.
5. Keep at most one active run per fixed target.
6. Inspect the latest runs for:
   - run status
   - process log
   - engagement `log.md`
   - `scope.json`
   - `findings.md`
   - `report.md` if present
   - `cases.db`
   - `surfaces.jsonl`
   - crawler output and crawler error logs
5. Identify:
   - logic bugs
   - runtime failures
   - stalled workflows
   - state inconsistencies
   - low-coverage collection failures
   - regressions in orchestrator visibility
6. Fix every confirmed issue discovered in that cycle.
7. Run targeted verification for each fix.
8. Create one local git commit for the cycle.
9. Do not push.
10. Record the cycle result to local state.

## Orchestrator Lifecycle

Use the local orchestrator helpers under `/Users/cis/dev/projects/RedteamOpencode/orchestrator/`:

- `./orchestrator/run.sh`
- `./orchestrator/stop.sh`

If a cycle changes orchestrator/backend/frontend/runtime/container wiring, restart with:

```bash
./orchestrator/run.sh --rebuild
```

Do not assume a plain restart is sufficient after code changes that affect the orchestrator image/runtime.

## Non-Interactive Rules

- Never ask for confirmation.
- Never stop at analysis if a fix is feasible in the current repo.
- Never open PRs or push.
- Never commit secrets, tokens, local state, or cycle artifacts to the public repo.

## Failure Classification

Each inspected run should be classified into one or more buckets:

- `runtime_start_failure`
- `crawler_failure`
- `collection_failure`
- `queue_stall`
- `phase_state_drift`
- `artifact_drift`
- `ui_visibility_bug`
- `model_config_bug`
- `auth_seed_bug`
- `other_confirmed_bug`

## Minimum Bug Checks

Every cycle must explicitly check:

- all-in-one runtime actually starts
- correct model/provider is applied
- katana produces usable output
- `katana` and `katana-xhr` usage/signals are explicitly checked in observed-path sources, `cases.db` source counts, and crawler output
- crawler health and crawler-derived coverage are plausible for the current run stage
- when a benchmark file is configured for a target, recall / precision / F1 are evaluated from the recorded findings versus that benchmark, with special attention to the local fixed target `http://127.0.0.1:8000`
- observed path types are populated when `cases.db` has typed rows
- if `Observed path types` is too sparse relative to `cases.db`, investigate crawler ingestion / observed-path derivation bugs
- if most observed paths are not crawler-derived (`katana` / `katana-xhr`), investigate crawler coverage bugs instead of treating it as healthy
- if `katana_output.jsonl` has data but neither `katana` nor `katana-xhr` show up in observed paths / `cases.db`, treat that as a crawler bug focus area
- if `katana_output.jsonl` has data but `surfaces.jsonl` / observed paths stay thin, treat that as a crawler bug focus area
- `/runs` and `/summary` agree on terminal vs non-terminal state
- `run.json.updated_at` advances with new events
- `current action`, `phase waterfall`, and `agents` reflect active work
- `processing` cases do not remain orphaned without a matching subagent dispatch
- stalled runs are failed and cleaned up
- terminal runs have an explicit stop reason
- benchmark-driven recall / precision improvements must come from general detection / correlation / execution / reporting quality, never from target-specific hardcoded answers, challenge lists, or Juice-Shop-only rules

## Stop Conditions For A Single Cycle

A cycle should start by analyzing the latest fixed-target runs and their logs.

If the current runs are healthy and no confirmed bug is found, end the cycle as a skip and let those runs continue.

A cycle ends in one of these two ways:

1. **Skip / no action needed**
   - the current runs are healthy or still progressing normally,
   - no confirmed actionable bug was found,
   - no new replacement runs are created.

2. **Bug-fix cycle**
   - a confirmed fixable bug was found from the observed runs,
   - every confirmed fixable bug discovered in that cycle was addressed and verified,
   - stale affected runs were stopped/deleted before fresh verification runs were created,
   - a local git commit was created.

## Local-Only Storage

All state for this loop must remain under `local-openclaw/`, which is ignored by git.

Recommended local files:

- `local-openclaw/state/optimizer-state.json`
- `local-openclaw/state/latest-context.md`
- `local-openclaw/logs/*.log`
