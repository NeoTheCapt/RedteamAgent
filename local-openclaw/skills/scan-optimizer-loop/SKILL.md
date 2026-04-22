---
name: scan-optimizer-loop
description: Use when OpenClaw is running a local unattended scan-optimization cycle that must inspect runs, fix bugs, improve challenge recall, review code quality, and commit locally without any user interaction.
---

# Scan Optimizer Loop

## Overview

This skill drives one unattended optimization cycle for RedteamOpencode.

It assumes a separate scheduler invokes OpenClaw periodically. This skill handles one cycle only.

**Primary optimization target:** The **RedTeam Agent project** (`agent/`, `orchestrator/`, root scripts). Fix `local-openclaw/` controller bugs if found.

Each cycle has three sequential phases:
1. **Bug Detection & Fix** — inspect runs, fix confirmed bugs in RedTeam Agent code
2. **Challenge Score Analysis & Recall Improvement** — analyze Juice Shop challenge completion, improve agent detection/exploitation to increase recall
3. **Code Review & Optimization** — review and clean up RedTeam Agent code touched in this cycle

## Inputs

Read:

- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/requirements/scan-optimizer-loop.md`
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/state/optimizer-state.json` if present
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/state/latest-context.md` if present
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/recall-analysis/*.md` — all prior recall analysis reports (cumulative knowledge, build on prior work)

Use:

- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/create_runs.sh`
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/build_context.sh`
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/update_cycle_state.sh`

## Fixed Workflow

### Phase 1: Bug Detection & Fix

1. Ensure orchestrator is reachable.
2. Build a local context snapshot from the latest fixed-target runs before taking action.
3. Inspect logs, runtime records, engagement artifacts, queue state, crawler output, and UI-visible state.
4. If the latest fixed-target runs are healthy and no confirmed bug is visible, proceed to Phase 2.
5. If a run is abnormal or has been running longer than 15 minutes with confirmed buggy behavior, identify confirmed repo-fixable bugs only. Do not speculate.
6. Fix every confirmed issue in the **RedTeam Agent code** (`agent/`, `orchestrator/`, root scripts).
7. Before verification, stop/delete the stale affected runs and their runtime/container, then create fresh replacement runs.
8. Run targeted verification for each fix. Do NOT commit yet.

### Phase 2: Challenge Score Analysis & Recall Improvement

9. If the local run is `completed`, read the `## Local Challenge Score` section from `latest-context.md`. This contains the ground-truth Juice Shop challenge completion from `/api/Challenges`.
10. Read all prior recall analysis reports from `local-openclaw/recall-analysis/` to build on existing knowledge — do NOT repeat prior analysis.
11. Analyze unsolved challenges (focus on difficulty 1-3). Diagnose each gap: detection gap, missing attack vector, execution bug, or reporting gap.
12. Write a detailed recall analysis report to `local-openclaw/recall-analysis/YYYY-MM-DD-<cycle_id>.md`.
13. **MUST implement 1-2 precise code fixes** targeting specific unsolved challenges. Analysis without code change is not allowed. Fixes must be general-purpose. **Simplify, don't complexify** — prefer removing unnecessary conditions over adding new ones. Never bloat agent prompts; fix bugs in scripts/tools instead. Net line delta for prompt files must be ≤ 0. If recall regressed vs peak, REVERT harmful changes first.
14. If the local run has not completed yet (score deferred), skip this phase.
15. Do NOT commit yet.

### Phase 3: Code Review & Optimization

14. Review RedTeam Agent code touched during Phase 1 and Phase 2, plus closely related code.
15. Look for: duplication, dead code, simplification opportunities, consistency issues, unnecessary abstractions.
16. Scope: `agent/`, `orchestrator/`, `tests/`, root scripts, and `local-openclaw/` if bugs are found. Test scripts go in `tests/agent-contracts/`, NOT in `agent/scripts/`.
17. Only clean up code directly related to this cycle's changes.
18. Verify every change.

### Commit & Finish

19. If any changes were made across all three phases, create one local git commit summarizing the full batch.
20. Update local cycle state.
21. If no changes were made, exit with `NO_ACTIONABLE_BUG_HEALTHY_RUNS`.
22. Do not push.

## Orchestrator Lifecycle

When verification requires restarting the local orchestrator, use:

- `./orchestrator/run.sh`
- `./orchestrator/stop.sh`

If code changes affect the orchestrator/runtime image or wiring, use:

```bash
./orchestrator/run.sh --rebuild
```

When creating a fresh local (Juice Shop) run for verification:

```bash
FORCE_REPLACE_ACTIVE_RUNS=1 TARGET_FILTER=local local-openclaw/scripts/create_runs.sh
```

**NEVER run `docker restart juice-shop` yourself.** The controller handles Juice Shop restart exclusively in the post-cycle step to preserve challenge score data.

## Hard Rules

- No user interaction.
- No partial "I'll fix later" output. Fix what is confirmed and feasible now.
- No push.
- Primary target is the RedTeam Agent project. Fix `local-openclaw/` controller bugs if found.
- No public-repo documentation updates for local loop state.
- Keep local automation artifacts under `local-openclaw/` only.
- Complete Phase 1 before Phase 2. Complete Phase 2 before Phase 3. Commit only after all three phases.

## Required Investigation Areas

For each cycle, explicitly check:

- orchestrator run creation and lifecycle
- all-in-one container startup
- model/provider wiring
- crawler health and crawl coverage
- case ingestion and type distribution
- `processing -> done/requeue` consumption
- surface coverage progression
- `Observed path types` sufficiency and source mix
- if observed path types are too sparse, or if most observed paths are not crawler-derived, deep-dive crawler bugs first
- state consistency across:
  - `/runs`
  - `/summary`
  - `run.json`
  - `scope.json`
  - `log.md`
- terminal reason clarity
- UI visibility regressions

## Verification Standard

Before finishing the cycle:

- run the smallest relevant automated tests
- run `git diff --check`
- ensure the latest fixes correspond to observed failures from the inspected runs

## Reporting Language

When the cycle finishes, print the final summary **in Chinese**. The controller extracts sections by matching these Chinese titles — keep them stable:

1. 检查的任务 ID
2. 确认修复的 bug（Phase 1）
3. 准招分析与改进（Phase 2）
4. 代码审查与优化（Phase 3）
5. 已执行的验证
6. 本地提交 ID

## Commit Rule

Create exactly one local commit per cycle summarizing all changes from all three phases.

Do not push.
