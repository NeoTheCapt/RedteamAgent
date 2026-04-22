# Requirements: redteam-auditor-hermes

## Scope

### In scope
- **Red Team Agent** (`agent/`, `orchestrator/`, root scripts): bug detection, recall improvement, code review
- **Orchestrator API contracts**: all REST endpoints under `/auth`, `/projects`, `/projects/{id}/runs`, and sub-resources
- **Orchestrator backend/runtime logs**: uvicorn log, engagement process logs, Hermes agent logs
- **Orchestrator feature validation**: Plan 5 config injection — `crawler_json`, `parallel_json`, `agents_json` → container env
- **Orchestrator Web UI** (via browser automation): 12 functional checks covering the full user journey
- **Benchmark recall**: Juice Shop challenge recall history; regression detection vs peak

### Out of scope
- Production targets (OKX or any live internet system) — audit covers only lab/local infrastructure
- Secrets management, credential rotation, or access control policy changes
- Infrastructure provisioning outside the existing `orchestrator/run.sh` lifecycle
- Any changes to `local-openclaw/` audit scripts that would suppress or exclude findings

## Guardrails

**MUST NOT:**
- Modify an audit script to exclude a finding it discovered
- Change test expectations to match broken behavior
- Add feature flags or conditional logic that hides a bug from audit
- Push any commit to a remote repository
- Restart Juice Shop (`docker restart juice-shop`) — the cycle controller owns this
- Emit findings about issues that cannot be confirmed via code tracing (no speculation)
- Exceed 8 fix commits + 2 review commits per cycle

**MUST:**
- Verify every fix locally before committing
- Record `manual_review_needed` on any finding where 3 verify attempts fail
- Roll back all commits (`git reset --hard baseline_sha`) if Phase 3 detects a regression
- Write `auditor-state.json` with the full cycle result regardless of exit status
- Save playwright screenshots for every `orch_ui` finding

## Success Metrics

1. `findings_after.total < findings_before.total` (net reduction)
2. `regression_count == 0` (no new bugs introduced)
3. All fix commits pass their local test
4. `findings_after` contains no `critical` severity items (critical must be fixed or escalated)
5. `auditor-state.json` `exit_status` is `ok` or `ok_no_fixes`

## Fallbacks

| Condition | Action |
|-----------|--------|
| Orchestrator unreachable at prep time | Set `exit_status=orchestrator_down`; skip orch_api, orch_log, orch_feature, orch_ui; still run agent_bug and agent_recall |
| Benchmark stale (>24h) | Trigger a fresh juice-shop run via `create_runs.sh`; wait up to 5 min for completion; if still not complete, skip agent_recall with a deferred note |
| `findings-before.json` absent at agent start | Agent constructs it from scratch using the 6 sources directly |
| Single finding verify fails 3 times | Mark `skipped: manual_review_needed`; continue with remaining findings |
| Phase 3 regression detected | `git reset --hard baseline_sha`; write `exit_status=blocked_regression`; still complete Phase 4 review on the rolled-back tree |
| Browser automation cannot connect to `http://127.0.0.1:18000` | Mark all 12 orch_ui checks as `orch_ui_unavailable`; skip UI findings; continue with other sources |
| Cycle exceeds 20 min wall clock | Write `exit_status=hermes_timeout`; commit any completed fix commits before aborting |

## Required Scheduler Env Keys (inherited from scan-optimizer)

The following keys must be present in `local-openclaw/state/scheduler.env`:

```
ORCH_TOKEN=<bearer_token>
PROJECT_ID=<integer>
ORCH_BASE_URL=http://127.0.0.1:18000
TARGET_OKX=https://www.okx.com
TARGET_LOCAL=http://127.0.0.1:8000
OPENCLAW_TIMEOUT_SECONDS=1200
```

New keys required only by the auditor:

```
HERMES_SKILL=redteam-auditor-hermes
HERMES_TOOLSETS=terminal,file,skills,browser,web,vision
HERMES_SOURCE_TAG=redteam-auditor
```

Note: the Hermes browser automation toolset is called `browser` (not
`playwright`). `hermes_openclaw_compat.sh` now auto-defaults the auditor skill
to `terminal,file,skills,browser,web,vision` when `HERMES_TOOLSETS` is unset, so
the scheduler.env override is optional.
