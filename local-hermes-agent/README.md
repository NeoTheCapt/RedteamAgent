# Local OpenClaw Automation

This directory is local-only and ignored by git.

It contains:

- requirements for the unattended scan-optimizer loop and unified auditor cycle
- reusable skills for OpenClaw/Hermes
- helper scripts for creating runs, building local context, and auditing the Orchestrator

Expected external runner responsibilities (now also available via the local controller script):

1. set `ORCH_TOKEN` and `PROJECT_ID`
2. invoke `local-hermes-agent/scripts/run_cycle_prep.sh` (scan-optimizer) or `audit_cycle_prep.sh` (unified auditor)
3. run Hermes with the appropriate skill and the generated prompt file
4. after fixes and verification, call `local-hermes-agent/scripts/update_cycle_state.sh <commit>`

Or use the integrated controller:

```bash
ORCH_TOKEN=... PROJECT_ID=... local-hermes-agent/scripts/run_cycle.sh
```

This performs the full cycle end-to-end and writes per-cycle logs and a Markdown report under `local-hermes-agent/logs/cycles/<timestamp>/`.

## Unified Auditor Cycle

The `redteam-auditor-hermes` skill replaces and extends `scan-optimizer-hermes` with full Orchestrator coverage.

### What it does (4 phases)

1. **Discover** — collect findings from 6 oracle sources:
   - `agent_bug`: recent engagement run logs and runtime errors
   - `agent_recall`: Juice Shop benchmark recall history and regressions
   - `orch_api`: probe every REST endpoint (create/read/update/delete + auth + 404 checks)
   - `orch_log`: scan uvicorn, process.log, and Hermes agent logs for exceptions and 5xx
   - `orch_feature`: verify Plan 5 config (`crawler_json`, `agents_json`) injects into container env
   - `orch_ui`: browser-based UI checks (12 checks spanning dashboard, progress, edit/new-run flows, STOP, and Documents/Events/Cases tabs)
   All findings merged into `audit-reports/<cycle_id>/findings-before.json`.

2. **Fix** — autonomously fix the top 8 findings; each fix gets its own commit
   (`fix(audit-<category>): <FND-id> <root_cause>`).

3. **Re-verify** — rerun all audit scripts + playwright; compute `fixed` and `regression` sets.
   If any regression → `git reset --hard baseline_sha`.

4. **Code review** — holistic review of all commits from this cycle; 1–2 cleanup commits if needed.

### How to enable

```bash
launchctl load /Users/cis/dev/projects/RedteamOpencode/local-hermes-agent/launchd/com.neothecapt.redteamopencode.auditor.plist
```

Runs every 30 minutes. Timeout: 20 minutes per cycle.

### How to disable scan-optimizer if superseding

```bash
launchctl unload /Users/cis/dev/projects/RedteamOpencode/local-hermes-agent/launchd/com.neothecapt.redteamopencode.scan-optimizer.plist
```

Leave both loaded if you want both cycles to run in parallel (they use separate state files and log paths).

### Where to find reports

- Per-cycle audit findings: `local-hermes-agent/audit-reports/<cycle_id>/findings-before.json`
- Post-fix verification: `local-hermes-agent/audit-reports/<cycle_id>/findings-after.json`
- Code review: `local-hermes-agent/audit-reports/<cycle_id>/review.md`
- Cycle controller report: `local-hermes-agent/logs/cycles/<cycle_id>/report.md`
- Auditor state: `local-hermes-agent/state/auditor-state.json`

### Required scheduler.env keys

The `LOCAL_HERMES_ENV_FILE` must point to a file with at minimum:

```bash
ORCH_TOKEN=<bearer_token>
PROJECT_ID=<integer>
ORCH_BASE_URL=http://127.0.0.1:18000
TARGET_OKX=https://www.okx.com
TARGET_LOCAL=http://127.0.0.1:8000
HERMES_TIMEOUT_SECONDS=3000  # auditor; scan-optimizer can use 1200
```

The plist additionally sets `HERMES_SKILL`, `HERMES_TOOLSETS`, and `HERMES_SOURCE_TAG`
as `EnvironmentVariables` so they do not need to appear in the env file.

## Single-Cycle Prep

Use:

```bash
ORCH_TOKEN=... PROJECT_ID=... local-hermes-agent/scripts/run_cycle_prep.sh
```

This will:

1. create the two fixed runs
2. wait for the configured observation window
3. build a fresh local context snapshot
4. write a prompt file for OpenClaw

Generated files:

- `local-hermes-agent/state/latest-created-runs.json`
- `local-hermes-agent/state/latest-runs.json`
- `local-hermes-agent/state/latest-context.md`
- `local-hermes-agent/state/hermes-prompt.txt`

## Suggested OpenClaw Invocation

The controller uses the local OpenClaw agent CLI (override with `HERMES_BIN` if needed):

```bash
"$HERMES_BIN" agent \
  --session-id local-hermes-agent:<cycle-id> \
  --message "$(cat local-hermes-agent/state/hermes-prompt.txt)"
```

The prompt itself tells OpenClaw to use the local `scan-optimizer-loop` skill.

## Local Scheduler (macOS launchd)

Scheduler management:

```bash
local-hermes-agent/scripts/manage_launchd.sh install    # install + load
local-hermes-agent/scripts/manage_launchd.sh uninstall  # unload + remove
local-hermes-agent/scripts/manage_launchd.sh status     # check if loaded
```

Before installing the LaunchAgent, copy and fill the env file:

```bash
cp local-hermes-agent/state/scheduler.env.example local-hermes-agent/state/scheduler.env
chmod 600 local-hermes-agent/state/scheduler.env
```

Then install/load the scheduler:

```bash
LOCAL_HERMES_INTERVAL_SECONDS=1800 local-hermes-agent/scripts/manage_launchd.sh install
```

Each scheduled cycle writes a detailed report to:

- `local-hermes-agent/logs/cycles/<timestamp>/report.md`

Optional chat summary delivery can be enabled by setting these in `local-hermes-agent/state/scheduler.env`:

```bash
REPORT_CHANNEL=discord
REPORT_TO=user:<discord_user_id>
```

For Discord DM delivery to Brian, the target shape would typically be:

```bash
REPORT_CHANNEL=discord
REPORT_TO=user:702445415840088086
```

## Orchestrator Lifecycle

Use the local orchestrator helpers under:

- `/Users/cis/dev/projects/RedteamOpencode/orchestrator/run.sh`
- `/Users/cis/dev/projects/RedteamOpencode/orchestrator/stop.sh`

When code affecting the orchestrator/runtime has changed, restart with a rebuild:

```bash
./orchestrator/run.sh --rebuild
```

Use plain start/stop only when a rebuild is not needed.

## Environment Variables

- `ORCH_TOKEN`: required
- `PROJECT_ID`: required
- `ORCH_BASE_URL`: optional, default `http://127.0.0.1:18000`
- `TARGET_OKX`: optional, default `https://www.okx.com`
- `TARGET_LOCAL`: optional, default `http://127.0.0.1:8000`
- `OBSERVATION_SECONDS`: optional, default `300`
