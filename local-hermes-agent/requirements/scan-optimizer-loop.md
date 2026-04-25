# Scan Optimizer Loop

## Purpose

Provide a local-only automation contract for OpenClaw to continuously improve RedteamOpencode scan quality.

This loop is not a scheduler. OpenClaw or another local runner calls it on a fixed cadence.

## Optimization Target

All code changes in every cycle target the **RedTeam Agent project**:
- `agent/` — agent prompts, skills, scripts, references, docker
- `orchestrator/` — backend, frontend
- Project root scripts — `install.sh`, etc.

The `local-hermes-agent/` directory is the controller itself — it is maintained separately and must NOT be modified by the optimization cycle.

## Fixed Targets

Each optimization cycle manages exactly two fixed targets with different lifecycle rules:

### OKX (`https://www.okx.com`)

OKX runs are long-lived observation runs. They should stay `running` continuously.

- If `queued` or `running`, leave it alone — this is normal.
- If `completed`, `failed`, `error`, `stopped`, `cancelled`, or `timeout`, treat as abnormal: the controller deletes it and creates a fresh replacement. Investigate why the run terminated and fix the underlying bug if needed.
- `completed` is NOT normal for OKX — it means the agent stopped scanning prematurely.

### Local / Juice Shop (`http://127.0.0.1:8000`)

Local runs are finite and expected to reach `completed` status.

- If `queued` or `running`, leave it running. Do not evaluate benchmark on an incomplete run.
- If `completed`, this is the expected state for benchmark evaluation. The controller gates benchmark evaluation on this status.
- If `failed`, `error`, `stopped`, `cancelled`, or `timeout`, treat as abnormal: fix the underlying bug, delete the broken run, and create one fresh replacement.

### Common rules

- Keep at most one active run per fixed target.
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
6. Fix every confirmed issue in the **RedTeam Agent code** (`agent/`, `orchestrator/`, root scripts). Never modify `local-hermes-agent/`.
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
- when the local run reaches `completed` status, the controller queries the Juice Shop `/api/Challenges` endpoint for the ground-truth challenge score. Analyze the unsolved challenges to improve recall. The controller defers scoring for in-progress runs.
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
- recall improvements must come from general detection / correlation / execution / reporting quality that would work against ANY web application, not just Juice Shop
- strictly prohibited: hardcoded endpoints/paths, hardcoded payloads, challenge-aware detection, target fingerprint shortcuts, known-answer injection, or rules disguised as generic but crafted to match only Juice Shop

## Cycle Phases

Each cycle has three sequential phases. Complete each before starting the next.

### Phase 1: Bug Detection & Fix

Analyze the latest fixed-target runs and their logs/artifacts.

- If the current runs are healthy and no confirmed bug is found, proceed to Phase 2.
- If a run is abnormal, fix the bug, verify, then proceed to Phase 2.

### Phase 2: Challenge Score Analysis & Recall Improvement

Only for completed local runs (Juice Shop).

- The controller queries `GET /api/Challenges` from the Juice Shop instance to obtain the ground-truth challenge completion status (solved/unsolved for all 111 challenges).
- Before each new local run, the controller restarts the Juice Shop container (`docker restart juice-shop`) to reset all challenge progress to zero. This ensures the score reflects only the current run's results.
- If the local run is completed and the challenge score is in `latest-context.md`:
  1. Analyze the unsolved challenges by category and difficulty.
  2. For each unsolved difficulty 1-3 challenge, diagnose the root cause: detection gap, missing attack vector, execution bug, or reporting gap.
  3. Implement concrete fixes in the **RedTeam Agent code** (agent prompts, skills, scripts, orchestrator) to improve recall.
  4. Fixes must be general-purpose vulnerability detection/exploitation improvements — never Juice-Shop-specific hardcoded answers.
- If the local run has not completed yet, this phase is a no-op.

### Phase 3: Code Review & Optimization

Only runs after Phase 1 and Phase 2 are resolved.

- Review code touched during Phase 1 and Phase 2, plus closely related code.
- Look for: duplication, dead code, simplification, consistency issues, unnecessary abstractions.
- Scope: `agent/`, `orchestrator/`, project root scripts. Do NOT review `local-hermes-agent/`.
- Only clean up code directly related to this cycle's changes.
- Every fix must be verified.

## Stop Conditions For A Single Cycle

A cycle ends in one of these ways:

1. **Skip / no action needed**
   - the current runs are healthy or still progressing normally,
   - no confirmed actionable bug was found across all three phases,
   - no code review issues were found,
   - no new replacement runs are created.

2. **Fix cycle**
   - bugs, benchmark regressions, or code review issues were found and fixed,
   - all fixes were verified,
   - stale affected runs were stopped/deleted if needed,
   - a single local git commit was created covering all three phases.

## Local-Only Storage

All state for this loop must remain under `local-hermes-agent/`, which is ignored by git.

Recommended local files:

- `local-hermes-agent/state/optimizer-state.json`
- `local-hermes-agent/state/latest-context.md`
- `local-hermes-agent/logs/*.log`
