---
name: redteam-auditor-hermes
description: "Unified Hermes auditor for the RedteamOpencode project. Runs one periodic cycle: discover bugs across Red Team Agent + Orchestrator + benchmark recall, fix everything in one batch, re-verify, and final code review."
---

# RedTeam Auditor (Hermes Unified Cycle)

## Purpose

One cycle covers the whole project (both Red Team Agent under `agent/` and Orchestrator under `orchestrator/`). Find problems from all 6 oracle sources, fix them all in one session, re-verify, then holistic code review. The previous scan-optimizer-loop's scope is fully absorbed — this replaces it.

## Scheduler / local controller notes

Periodic cycles currently run from the Hermes-local controller path `~/dev/projects/RedteamOpencode/local-hermes-agent` (newer replacement for older `local-openclaw` paths). The macOS LaunchAgent label used for scheduled auditor execution is `com.neothecapt.redteamopencode.auditor`; its scheduler env lives at `~/dev/projects/RedteamOpencode/local-hermes-agent/state/scheduler.env` and uses `LOCAL_HERMES_*` variables. Historical logs/artifacts may still contain `local-openclaw` noise; prefer the concrete cycle binding/controller path over stale hard-coded examples.

## Inputs

Read before starting:
- Prefer the concrete cycle binding from the user/controller for repo root, state dir, and audit report dir. Newer Hermes cycles may use `local-hermes-agent/...` while older notes use `local-openclaw/...`; do not hard-code one when the prompt supplies the other.
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/requirements/redteam-auditor-hermes.md` (or the controller-specified Hermes equivalent)
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/state/auditor-state.json` (if present — prior cycle state; use `local-hermes-agent/state/auditor-state.json` when supplied by cycle binding)
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/state/latest-context.md` (prep wrote this; use `local-hermes-agent/state/latest-context.md` when supplied)
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/audit-reports/<cycle_id>/*.json` (where cycle_id comes from context; use the bound audit report dir when supplied)

Prep scripts to call when needed:
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/create_runs.sh`
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/build_context.sh`
- `/Users/cis/dev/projects/RedteamOpencode/local-openclaw/scripts/update_cycle_state.sh`

## Fixed Workflow

### Phase 1 — Discover (no edits; only gather findings)

Gather findings from 6 sources into `audit-reports/<cycle_id>/findings-before.json`. Each finding has:
```json
{
  "id": "FND-001",
  "category": "agent_bug|agent_recall|orch_api|orch_log|orch_feature|orch_ui",
  "severity": "critical|high|medium|low",
  "summary": "...",
  "evidence": { "file:line": "...", "command": "...", "output_excerpt": "..." },
  "suggested_fix_path": "agent/... | orchestrator/backend/... | orchestrator/frontend/..."
}
```

Sources:

**1. agent_bug** — inspect recent engagement runs. The cycle prep now preserves failed runs' engagement directories (KEEP_TERMINAL_RUNS=1), so the DB rows AND the on-disk evidence (log.md, run.json, cases.db, findings.md) are BOTH available. Sources to check, in priority order:

a. **Orchestrator runs API** — fetch `GET /projects/<PROJECT_ID>/runs` (token in `local-openclaw/state/scheduler.env::ORCH_TOKEN`). For every run whose `status` is NOT in {`queued`, `running`, `completed`}, emit an `agent_bug` finding citing `run.id`, `run.target`, `run.status`, and `run.stop_reason_text` (full text, not truncated — the stop reason is the primary diagnosis). Each failed/stopped/error run should produce exactly one finding unless its stop_reason_text matches a different category (e.g., an `orch_feature` code bug surfaced via a run failure).
b. **Engagement log.md** — for each failed run, open `<run.engagement_root>/workspace/engagements/*/log.md` and tail the last ~150 lines. Look for Python tracebacks, assertion errors, `stop_reason_code=runtime_error` markers, `REQUEUE_CANDIDATE` loops, or dispatcher-visible errors that clarify WHY the stop reason fired. Attach the top-N lines as `evidence` on the finding.
c. **run.json** — grep for `stop_reason_code: runtime_error` or any `stop_reason_code` value other than `completed` in any `run.json` under recent engagement roots. This catches runs where the orchestrator DB row might have been cleaned but the engagement directory was preserved.
d. **Workspace env** — check `workspace/.env` presence and content in the latest engagement root; missing expected keys is itself a finding, but evaluate them against project config: `KATANA_CRAWL_DEPTH` and provider/model env should be present when configured, while `REDTEAM_DISABLED_AGENTS` is only expected when `agents_json` actually disables one or more agents (it is correctly absent when all agents are enabled).

When a failed run's stop_reason_text clearly points at a product bug (e.g. `no such column consumed_at`, `Processing queue assignments ... had no matching active runtime agent`, `dispatcher reset-stale failed`), classify the finding with the appropriate category:
- SQL / DB schema error → `agent_bug` with `suggested_fix_path: agent/scripts/dispatcher.sh` or wherever the schema lives
- Orchestrator stall-detector false positive → `orch_api` or `agent_bug` (orchestrator side)
- Subagent prompt drift → `agent_bug` with the agent prompt file

Historical failed-run pitfall: the orchestrator API can keep returning old failed runs forever. If a failed run's `created_at`/`ended_at` predates the current baseline and the same fingerprint was already `status: fixed` in the immediately prior cycle, do **not** make a duplicate/category-mismatched fix just to silence the old row. Record the finding in Phase 1 as required, then in Phase 2 mark it `deferred` or `reclassified` with `reason` documenting the prior fix commit and absence/presence of newer reproductions. Only edit product code if a post-baseline run reproduces the same stop reason or the prior fix clearly did not cover the root cause.

**2. agent_recall** — the **authoritative** peak is `local-openclaw/state/benchmark-metrics-history.json` → `targets.<target>.peak.metrics.challenge_recall` (populated monotonically by `benchmark_gate.py`). Do NOT scrape peak numbers from `recall-analysis/*.md` or `latest-context.md` — those contain ephemeral scoring from scan-optimizer Phase 2 that is not a real benchmark event. Older cycles incorrectly cited an ephemeral "peak 0.162" (18/111) for http://127.0.0.1:8000; always trust the current `benchmark-metrics-history.json` peak for the target instead of any hard-coded example value.

**Low recall is a bug — but only when there is FRESH scored data this cycle.** When `last_metrics.challenge_recall` is below `peak.metrics.challenge_recall` AND `last_metrics.cycle_id` is THIS cycle (i.e. the local Juice Shop run completed and was just scored), that is a **real finding** to investigate and fix in Phase 2.

**If the local run is still mid-flight** (`last_metrics.cycle_id` is from a prior cycle, OR `latest-context.md` Local Challenge Score has `status: deferred`), do NOT emit a fresh recall finding this cycle. A half-finished run hasn't had time to solve everything it would naturally solve, so comparing partial recall to peak is meaningless — operator policy 2026-04-25: "跑一半就分析没有任何意义". Defer with reason `"local run still progressing; recall comparison reserved for the cycle in which the run completes"`. The controller only generates a `recall-analysis/<date>-<cycle>-regression.md` report when a new history entry lands, so the absence of that report is the fast signal that this cycle didn't score.

When you DO have a fresh scored run below peak, defer is ONLY legitimate when you can document, with evidence, that the regression is due to a factor outside repo code (e.g. target itself changed challenge set, benchmark endpoint unreachable). Do not defer with reason "no fresh benchmark available" — you are not verifying the fix by re-running the benchmark; you are shipping a root-cause fix.

**Timeline sanity check — MANDATORY before attributing cause.** If you think a specific commit caused the recall regression, run:

```bash
python3 local-openclaw/scripts/check_commit_predates_regression.py \
    --commit <suspect_sha> \
    --target <target_url_key_in_history>
```

If the script exits non-zero ("BLOCKED: suspect commit POSTDATES the recall drop"), that commit CANNOT be the root cause — its date is later than the first recall-below-peak event in `benchmark-metrics-history.json`. Pick a different commit that predates the drop, OR acknowledge the regression has no single-commit cause and mark the finding `deferred` with reason `"root cause predates all post-peak commits; recall regression is baseline, not a regression this cycle can attribute"`. Do NOT proceed with the attribution.

Prior-cycle example of the failure this rule prevents: cycle `20260424T041427Z` committed `5793ded` claiming `8abdab7` (Apr 23) caused a recall drop from 0.117 → 0.036. But that drop happened Apr 13, ten days before `8abdab7` existed. Hermes satisfied "investigate root cause" with shallow correlation instead of checking dates.

Record the script's exit line verbatim in the finding's `evidence.timeline_check` field so the validator can confirm the check ran.

**Investigation checklist** (produce at least two of these before deciding what to edit):
- Run `python3 local-openclaw/scripts/recall_regression_report.py --target http://127.0.0.1:8000` and read its output (written under `local-openclaw/recall-analysis/<date>-<cycle_id>-regression.md`). The report mechanically diffs the current solved-challenge set against the peak solved set stored in `benchmark-metrics-history.json` — no human interpretation, just names. If the helper exits 2 with "peak has no solved_challenge_names", the peak predates the solved-list persistence that `benchmark_gate.py` added on 2026-04-25; in that case fall back to reading the newest hand-written `local-openclaw/recall-analysis/*.md` (last one dated 2026-04-13) as a stale reference and note the gap in your finding.
- For each regressed challenge, `grep -rn "<challenge id/name>" agent/skills/` to find which skill is supposed to handle it. Did that skill's prompt or methodology change recently? `git log -p agent/skills/<name>/SKILL.md`.
- Read 2–3 recent engagements' `log.md` for the regressed challenge category. Is the right subagent being dispatched? Is the fuzzer/vulnerability-analyst actually hitting the right surface?
- Check `agent/.opencode/prompts/*` for drift in dispatch rules (surface-type → agent mapping).

**Commit-worthy fixes for recall regression** include (pick whichever matches the evidence):
- Adding a missing skill methodology step that was present at peak but is missing now
- Restoring a dispatch rule that regressed (e.g. a previous audit cycle's category-mismatched commit wiped it — check F2 cross-cycle regression first)
- Fixing a surface-to-agent mapping bug in `agent/.opencode/prompts/agents/operator.txt`
- Fixing a concrete bug in `scripts/append_surface_jsonl.sh` / `dispatcher.sh` / `case-dispatching/SKILL.md` that the log evidence shows caused the miss
- Updating the skill's `## Checklist` to cover a class of challenges that regressed

Reverify_scope for recall fixes is `pending_new_run` (agent/skills/** changes only affect runs created AFTER the commit; auditor is forbidden from creating runs). Status stays `fixed` if the skill/prompt edit includes a concrete behavioral change backed by evidence from a regressed challenge; otherwise `deferred` with the specific blocker documented.

**3. orch_api** — findings already in `audit-reports/<cycle_id>/api.json` (written by prep). Read and fold in.

**4. orch_log** — findings in `audit-reports/<cycle_id>/logs.json` (written by prep). Read and fold in.
- Scope-filter them before treating them as product bugs: if a log hit comes from global Hermes infrastructure (for example `~/.hermes/logs/*`) and you cannot trace it back to RedteamOpencode repo code, mark it `reclassified` or `deferred` in `findings-after.json` instead of forcing a product-code fix.
- If the audit helper itself is malformed (for example shell arithmetic/count parsing bugs that corrupt the audit result), you may repair that local helper for cycle correctness — but do NOT edit it merely to hide a real finding.

**5. orch_feature** — findings in `audit-reports/<cycle_id>/features.json` (written by prep). Read and fold in.

**6. orch_ui** — YOU do this with the `browser` toolset (Hermes Playwright integration). If `browser` isn't in the session's toolsets, record `orch_ui_unavailable` for every check; do NOT pretend to do them from the CLI.

**UI auth bootstrap (REQUIRED before any UI check).** The orchestrator frontend reads its session from `localStorage["redteam-orchestrator-session"]` = `{"token": "...", "username": "admin"}`. There is no shared password — do NOT attempt form-based login. Instead:
1. Read `ORCH_TOKEN` from `local-openclaw/state/scheduler.env` (line starts with `ORCH_TOKEN=`).
2. Navigate to `http://127.0.0.1:18000/`.
3. Inject the session via the browser page-eval facility (in Hermes this is `browser_console(expression=...)`):
   ```js
   window.localStorage.setItem(
     "redteam-orchestrator-session",
     JSON.stringify({ token: "<ORCH_TOKEN>", username: "admin" })
   );
   ```
4. Reload the page. If a login form still shows after reload, the token is invalid/expired — record one top-level finding with `result=token_invalid` and skip UI work (do NOT brute-force).

Practical token-handling note:
- Hermes file/terminal output may redact `ORCH_TOKEN` as a prefix/suffix preview (for example `abc...xyz`). Do NOT paste that redacted display string into `localStorage`; it will 401 in-browser even though shell commands that source the env file can still authenticate with the full hidden token.
- Before declaring `token_invalid`, validate the exact in-page token with a browser-console fetch such as `fetch('/projects', {headers:{Authorization:'Bearer <token>'}})` and confirm whether the browser is truly seeing 200 vs 401.
- If the displayed token is redacted, recover the full token from a non-redacted local artifact already produced by the scheduler/auditor flow (for example a prior cycle report or token helper artifact) before retrying the bootstrap.
- Practical Hermes fallback when the shell can authenticate but browser/tool output redacts the token: start a tiny localhost helper that reads `local-openclaw/state/scheduler.env` and serves the raw token on `http://127.0.0.1:<port>/token`, then use `browser_console(expression=...)` to `fetch()` that endpoint inside the page and write `localStorage["redteam-orchestrator-session"]` without ever pasting the secret through model-visible text. Verify with an in-page authenticated fetch before reloading.
- If the Hermes browser can reach the orchestrator port but cannot reach the helper port (`TypeError: Failed to fetch`), use a same-origin one-shot token handoff instead: from the shell, write the raw token to a temporary file under the already-served frontend dist (for example `orchestrator/frontend/dist/__hermes_session_token.txt`), use `browser_console` to `fetch('/__hermes_session_token.txt')`, set localStorage, verify `fetch('/projects', {Authorization})` returns 200, then immediately delete the temporary token file. Do not leave the token file on disk or stage it in git.
- `browser_vision` may fail model-side while still saving a screenshot path (for example `Unsupported value: 'temperature'` from the vision model). When it returns `success=false` with a `screenshot_path`, copy that file into `audit-reports/<cycle_id>/ui-screenshots/<check_id>-<short>.png` and use DOM/browser_snapshot evidence for the pass/fail decision.

Once authenticated, run ALL 12 checks in order.

| # | `check_id` | Name | What to verify |
|---|---|---|---|
| 1  | `ui-01` | Sidebar projects list          | Sidebar renders projects; hover shows Edit + Delete icons per row |
| 2  | `ui-02` | ProjectEditModal open          | Click Edit → modal opens with 6 tabs (Model/Auth/Env/Crawler/Parallel/Agents); each tab switchable |
| 3  | `ui-03` | ProjectEditModal persist       | Crawler tab: set `KATANA_CRAWL_DEPTH=16`, Save, re-open → value persisted |
| 4  | `ui-04` | NewRunForm advanced submit     | "Create new project" → expand Advanced → fill Model/API key/base URL → submit → project appears in Sidebar |
| 5  | `ui-05` | Inherited config summary       | Selected project shows "Inherited from project" summary with working Edit link |
| 6  | `ui-06` | Run delete flow                | Current UI behavior exercises the project delete icon in the sidebar: Delete icon → ConfirmDialog → Cancel keeps; Confirm deletes; verify `GET /projects/<project_id>` returns 404 after |
| 7  | `ui-07` | STOP transition                | STOP button on running run → ribbon goes amber within 10s (not red, not silent). **Operator policy 2026-04-25 — healthy runs are sacred**: never stop a healthy fixed-target run (okx.com, 127.0.0.1:8000) just to test the UI transition. Healthy = `status=running` with no errors in its log. Pick the STOP target from this strictly-preferred order: (1) a throwaway run from `audit_orchestrator_features.py` (target `http://127.0.0.1:8000` under a `__audit-features-test__*` project — features.py is going to stop it anyway, ride along); (2) a redundant run when a fixed target has 2+ running (stop the older one); (3) if neither is available, mark ui-07 `skipped` with notes `"no expendable run; healthy fixed-target runs preserved per operator policy"`. Do NOT stop a sole-runner against a fixed target even if you intend to follow up with `POST /runs` — the validator now treats running=0 + no acknowledged blocker as a contract violation, and recreation belongs to the controller's post-Hermes block, not to a UI test. Anti-pattern: cycles 20260425T054522Z..111827Z stopped 7 consecutive okx runs (#678..#709), and the okx target was effectively never in steady state. |
| 8  | `ui-08` | Documents tab                  | Tree shows buckets; click a `.md` → rendered via react-markdown |
| 9  | `ui-09` | Events tab pause               | Click Pause → new events do NOT appear (neither WS nor REST seed) |
| 10 | `ui-10` | Cases keyboard nav             | Tab-focus a row, Enter activates side panel |
| 11 | `ui-11` | Progress phase content         | Progress tab shows 5 phase cards (recon / collect / consume_test / exploit / report); EACH card shows phase-specific content (recon=crawl targets, collect=surface list, consume_test=case queue, exploit=findings list, report=final pointer). Flag "only Report has content, borrowed from another phase". |
| 12 | `ui-12` | Agent participation breakdown  | Dashboard + Progress must show explicit agent count AND per-type breakdown including parallel dispatches (e.g. `2× vulnerability-analyst, 1× exploit-developer`). Absence is a `medium` finding. |

**Evidence requirements (REQUIRED, not optional):**

For EACH of the 12 checks, save a screenshot to `audit-reports/<cycle_id>/ui-screenshots/<check_id>-<short-name>.png` — even when the check PASSES. No exceptions:
- Pass case: prove you actually loaded the page.
- Fail case: prove what you saw.
- Unavailable case: prove the page/control didn't load.
- Hermes/browser practical note: if `browser_vision` captures a `screenshot_path` but model-side vision analysis fails, the screenshot is still valid evidence. Copy that path into the required `ui-screenshots/` filename and record the DOM/browser_snapshot evidence separately for pass/fail.

**Structured per-check record in `source-status.json`:**

```json
{
  "orch_ui": {
    "status": "found|clean|unavailable|skipped|error",
    "count": <number of failed checks>,
    "notes": "<one-line overall>",
    "checks": [
      {
        "check_id": "ui-01",
        "name": "Sidebar projects list",
        "result": "passed|failed|unavailable|skipped",
        "screenshot": "ui-screenshots/ui-01-sidebar.png",
        "finding_id": "FND-XYZ or null",
        "notes": "<one-line observation>"
      },
      ... one entry per check_id ui-01 through ui-12 ...
    ]
  }
}
```

**Hard rules:**
- Do NOT mark `result: passed` unless you actually loaded the target page AND saved a screenshot for that check_id. If you ran out of tool budget before a check, mark it `result: skipped` — do NOT pretend it passed.
- Do NOT write a `finding_id` that doesn't exist in `findings-before.json`.
- `orch_ui.status = "clean"` requires ALL 12 checks to have `result: passed`. Otherwise use `found` (with failed count), `skipped` (some unrun), or `unavailable`.
- Practical verification notes from 20260424T003942Z:
  - `ui-01`: `browser_vision` can miss tiny sidebar edit/delete icons; confirm against `browser_snapshot` / accessibility tree before calling a failure.
  - `ui-09`: a screenshot alone cannot prove the Events stream is paused; verify the Pause→Resume toggle plus stable `.event-row` count/tail over a short timed wait.
  - `ui-10`: after Tab-focusing a cases-table row and pressing Enter, confirm the side panel via DOM (`.case-side` / `aria-label="Case <id>"`) if the compact snapshot truncates the right pane.
  - `ui-02`/`ui-03`: hidden React `<dialog>` / confirm-dialog nodes may remain in the DOM with `display:none` after cancel/close. Do not treat `document.querySelector('.confirm-dialog')` existing as an active blocker, and do not diagnose ProjectEditModal tab switching while a visible dialog is still open. Check `getComputedStyle(dialog).display !== 'none'`, then re-open the modal and click tabs with a short wait before calling a failure.
  - `ui-07` reverify pitfall: the STOPPING state can be brief in real browsers even after the fix. After clicking STOP, grab `browser_snapshot` / DOM text immediately and only then take the screenshot; `browser_vision` alone can miss the amber STOPPING badge and capture the later STOPPED state instead.
  - If the authenticated shell reports `0 runs`, treat run-scoped checks (`ui-07` through `ui-12`) as `skipped`, not `failed`; still save screenshots for each skipped check and cite the `0 runs` shell evidence in `source-status.json`. **BUT**: 0 runs with a healthy orchestrator also means prep's `recover_abnormal_runs` failed to create a run this cycle — that IS a bug. Emit an `agent_bug` finding `recovery_did_not_create_run` citing the cycle's prep log (expect `no latest run exists` + `recover_abnormal_runs` attempts); do NOT silently absorb 0-runs as normal. The infrastructure gate in `run_cycle.sh` already aborts the cycle when Docker is down, so seeing 0 runs here means recovery logic failed for non-infrastructure reasons.
  - Browser accessibility refs can become stale or hit the project row instead of the tiny edit/delete icon after sidebar refreshes. For sidebar/modal UI checks, prefer DOM clicks via `browser_console` using stable `aria-label` values (for example `Edit project <slug>` / `Delete project <slug>`) and verify visible dialogs with `getComputedStyle(...)` before deciding pass/fail.

For each failed check, also append a finding to `findings-before.json` with `category: "orch_ui"` and include the same `check_id` in its `evidence` field.

Finish Phase 1 by:
- Aggregating all findings; sort by (severity DESC, category)
- Cap at top N=8 for Phase 2
- Log remaining as `deferred` in `findings-before.json`
- Writing `audit-reports/<cycle_id>/source-status.json` with one entry per agent-side source (`agent_bug`, `agent_recall`, `orch_ui`) using these exact statuses:
  - `clean` — scan ran, nothing found
  - `found` — scan ran, findings present (include `count`)
  - `unavailable` — preconditions missing (e.g. browser toolset not loaded); include `reason`
  - `skipped` — deliberately not scanned; include `reason`
  - `error` — scan attempted but crashed; include `reason`
  - `not_run` — never got to it (only if you're being killed by timeout mid-phase; normally you should pick one of the above)

  **Never use `clean` when you didn't actually execute the scan.** The controller's Discord summary renders these statuses in Chinese ("已完成，0 发现" vs "未执行"), and misreporting `clean` hides gaps from the operator.

### Phase 2 — Fix All (max 8 commits)

**Priority order (non-negotiable):** sort open findings by severity `critical > high > medium > low`, tackle in that order. Never commit a medium/low fix while a high/critical is still open — defer lower work explicitly if needed.

**Clean-cycle exit is LEGAL:** if prep's three automated sources (`orch_api`, `orch_log`, `orch_feature`) all pass, `agent_bug` finds no abnormal runs, `agent_recall` is stable or already-deferred, and all 12 `orch_ui` checks pass — set `auditor-state.json.exit_status = "ok_no_fixes"` and proceed directly to Phase 4 review. Do NOT fabricate a cosmetic finding to produce a commit.

**Fix-site match rule (non-negotiable):** every commit MUST touch a file that shares a directory prefix with the finding's `evidence.file:line` / `suggested_fix_path` / `evidence.run_json`. Example violations that ARE NOT acceptable:
- Finding cites `launcher.py:2704` queue_incomplete → diff touches only `agent/.opencode/prompts/*.txt` (regenerating prompts ≠ fixing a classification bug).
- Finding cites `frontend/src/components/progress/*.tsx` → diff touches only `backend/db.py`.
- Finding cites a failed run's `run.json` → diff touches only a markdown skill file.

If the right fix file is unclear after tracing, mark the finding `deferred` with `reason` documenting the blocker. Never fake a commit by editing a tangentially-related file.

Concrete bad example to learn from: cycle `20260423T134501Z` committed `8aed200` "rerender operator prompts" as the fix for FND-001 (queue_incomplete, evidence in launcher.py / run-0501/run.json). The commit regenerated `agent/.opencode/prompts/agents/operator.txt` instead. That is the exact anti-pattern this rule blocks.

**Stable fingerprint (REQUIRED field on every finding).** The per-cycle `FND-001..N` ids reset each cycle, so they can't be used for cross-cycle tracking. Every finding you write to `findings-before.json` / `findings-after.json` MUST also include a `fingerprint` field computed as:

```python
import hashlib
def fingerprint(category: str, summary: str) -> str:
    # Lowercase + collapse whitespace for stable hashing across minor
    # phrasing drift ("run 501 failed" vs "Run 501 failed with...").
    norm = " ".join((summary or "").lower().split())
    raw = f"{category}|{norm}"
    return f"{category}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
```

Examples:
- `agent_bug|Run failed with queue_incomplete stop_reason_text…` → `agent_bug-a8f1c2e49b33`
- `orch_ui|ui-07 STOP transition broken: clicking STOP leaves run running` → `orch_ui-3d82f7001c4a`

The fingerprint is the cross-cycle join key. Use it (not `FND-XXX`) in persistent-bug detection below.

**Persistent-bug detection** (do this BEFORE fixing any finding): for each finding you're about to fix, grep `local-openclaw/audit-reports/*/findings-after.json` (last 3 cycles) for a prior `status: fixed` entry with the same `fingerprint` (primary key) OR same `check_id` OR same `category` + substring-match `summary` (fallback keys for older cycles that didn't carry fingerprints). If found, the prior fix didn't work:
- Bump severity one level (medium → high, high → critical).
- In `evidence`, enumerate prior commit SHAs that claimed to fix it.
- For STOP / run-status / reconciler bugs: do NOT just patch the frontend optimistic update path. Check all of these before writing code:
  - `orchestrator/backend/app/services/runs.py::_reconcile_run_status` — is the status truly preserved across polls?
  - `orchestrator/backend/app/services/launcher.py::stop_run_runtime` — does it actually terminate the container? Error handling?
  - `orchestrator/backend/app/services/runs.py::update_run_status` "stopped" branch — does `stop_run_runtime` fail silently?
  - `orchestrator/backend/app/services/run_summary.py` — does the summary/dashboard projection also treat `stopped` as terminal, or is it still surfacing `scope.status=in_progress` / stale active agents from events or cases.db?
  - The supervise_container thread — can it flip status back?
  - `run.json` metadata written by `_write_run_terminal_reason` — does it agree with DB?
- Trace end-to-end: click STOP in UI → POST /status → DB write → runtime kill → next GET /runs → GET /runs/<id>/summary → dashboard/progress projection. Find where the chain breaks.

For each finding in top-N (in severity order):

**1. Root-cause** — grep symptom → trace to source file:line. Use the table below for quick routing:

| Category | Symptom | Likely root file |
|----------|---------|------------------|
| agent_bug | `stop_reason=runtime_error` | `agent/.opencode/prompts/agents/<name>.txt` |
| agent_recall | missing challenge class | `agent/skills/<category>/SKILL.md` |
| orch_api | 500 / schema mismatch | `orchestrator/backend/app/api/<resource>.py` or `services/<resource>.py` |
| orch_log | Traceback | services layer at frame top |
| orch_feature | config not injected | `orchestrator/backend/app/services/launcher.py` |
| orch_ui | button no-op | `orchestrator/frontend/src/components/<name>.tsx` |

**2. Apply patch** — Edit tool. Forbidden:
   - Changing audit scripts to exclude the finding
   - Changing test expectations to match broken behavior
   - Adding a feature flag to hide the bug
   - Fix the product code so the finding would not reproduce

**3. Verify locally** — must pass BEFORE moving to next finding:
   - Backend change → `cd orchestrator/backend && .venv/bin/python -m pytest tests/test_<touched>.py -q` passes
   - Frontend change → `cd orchestrator/frontend && npm test -- --run <touched>.test.tsx` passes
   - If audit source was a script → re-run that script, finding is PASS
   - If audit source was UI → re-run the specific playwright check, PASS

   If verify fails 3 times → revert the Edit, mark finding as `skipped: manual_review_needed`, move on.

**4. Commit** with message: `fix(audit-<category>): <FND-id> <root_cause_short>` PLUS a 2-3 line body that captures: (a) what the pre-fix reproducer showed, (b) what file:line(s) changed, (c) what post-fix evidence (test output, grep result, scan re-run) confirms the fix. The 2-line subject + body convention exists because the cycle's `summary.md` is gitignored and `findings-after.json` is per-cycle; the commit body is the only place a future `git log` can stand-alone explain WHY the change landed. Empty bodies are forbidden — meta-audit on 2026-04-27 found 13/13 audit-* commits in a 20-commit window had body=0, leaving the rationale invisible to anyone not reading the cycle artifacts.

### Phase 3 — Static Re-verify (+ bounded backend runtime re-verify)

**Honest scope statement.** Phase 2 commits land in the source tree but most of them don't take effect in the currently-running runtime:

| Fix lives in… | Re-verify in this cycle? | Why |
|---|---|---|
| `orchestrator/frontend/**` | ✅ yes — cycle already ran `npm run build`; uvicorn serves dist/ directly | frontend is file-served |
| `orchestrator/backend/**.py` | ⚠ only after an explicit uvicorn restart (see A below) | running uvicorn has stale in-memory bytecode |
| `agent/**` (scripts, prompts, skills) | ❌ NO — existing engagement workspaces have pre-cycle copies; only NEW runs would pick up the changes, and auditor is forbidden from creating runs | workspace snapshot at run-creation time |
| Static artifacts (findings files, schemas, docs) | ✅ yes | files are read fresh |
| Unit tests added in Phase 2 | ✅ yes | tests run against edited source directly |

**Do NOT claim a runtime-sensitive fix was "verified" when you only re-read a file or re-ran a static test.** A passing prep-script run against a stale uvicorn proves nothing.

**Static re-verify (always):**

1. Re-run the three prep scripts against whatever is currently live:
   - `bash local-openclaw/scripts/audit_orchestrator_api.sh <cycle_id>`
   - `bash local-openclaw/scripts/audit_orchestrator_logs.sh <cycle_id>`
   - `python3 local-openclaw/scripts/audit_orchestrator_features.py <cycle_id>`

   **Scope of the "no-new-runs" binding** (clarified 2026-04-25 after a Docker-down cycle misapplied it):

   Two of these helpers are mutating BY DESIGN: `audit_orchestrator_api.sh` creates/deletes a throwaway `__audit-*__` project + run as part of its probe sequence (`projects_create` → `runs_create` → `runs_stop` → `projects_delete`); `audit_orchestrator_features.py` does the same for env-injection validation (`cleanup_stale_audit_projects`, `POST /projects`, `POST /projects/{id}/runs`, cleanup). The "no-new-runs" rule in the cycle prompt applies to **Hermes's own actions in Phase 2** (don't craft a new orchestrator run as evidence for a finding fix); it does NOT apply to these two prep/reverify helpers — they are part of the sanctioned verification pipeline. Prep already runs both at cycle start without issue, and they clean up after themselves.

   Run them in Phase 3 reverify as normal **when Docker is healthy**. Skip them ONLY when:
   - `docker info` is unreachable (OrbStack stopped) — Layer-1 infrastructure gate should have already aborted the cycle, so Hermes never sees this case in practice
   - OR one of them has produced a traceback on a previous attempt this session — then record the specific failure in `review.md` and fall back to read-only checks for THAT helper's sources only

   Do NOT categorically skip them because their name includes "projects_create"; that was the 142549Z failure pattern where a Docker-down cycle misread the scripts' design as a policy violation and produced a `skipped_by_policy` fake-green instead of flagging the infrastructure outage.
2. Run any unit tests the Phase 2 commits added (from their commit diff).
3. Re-read the specific ui-XX browser check corresponding to any frontend finding. Frontend assets are live, so this DOES count as verification for UI fixes.
4. Merge all results into `findings-after.json`. Mark each finding's `reverify_scope` field with one of:
   - `"static_live"` — fix effect is already visible in the running system (frontend, file)
   - `"static_test"` — fix is covered by a unit test that's green, but runtime effect not yet observable
   - `"pending_restart"` — backend fix; scheduled for the bounded restart below
   - `"pending_new_run"` — agent fix; cannot verify this cycle; relies on next cycle

**Bounded backend runtime re-verify (only when the cycle diff touches `orchestrator/backend/**/*.py`):**

```bash
# Stop + restart uvicorn. ~2s API downtime. The SQLite DB persists.
bash orchestrator/stop.sh && bash orchestrator/run.sh
# Wait for healthz 200 before proceeding.
for i in $(seq 1 10); do
  curl -fsS http://127.0.0.1:18000/healthz >/dev/null 2>&1 && break
  sleep 1
done
# Re-run the prep scripts ONE more time against the fresh uvicorn.
bash local-openclaw/scripts/audit_orchestrator_api.sh <cycle_id>-reverify
bash local-openclaw/scripts/audit_orchestrator_logs.sh <cycle_id>-reverify
python3 local-openclaw/scripts/audit_orchestrator_features.py <cycle_id>-reverify
```

Outcome goes into `findings-after.json`: each finding previously marked `pending_restart` now has its `reverify_scope` updated to either `"runtime_restart_passed"` or `"runtime_restart_still_failing"`. Findings that still fail after restart should be reopened (status → `open`) — the fix did not actually work.

**Agent-code fixes — no runtime re-verify is possible:**

- Mark those findings `reverify_scope: "pending_new_run"` with `reason: "agent/ code only loads on new run creation; auditor cannot create runs"`.
- Status stays `fixed` IF Phase 2 added unit tests that pass against the edited source. The next cycle's natural `agent_bug` scan will catch real regressions.

**Regression guard (unchanged from prior design):** if `regression_count > 0` (new findings in after that weren't in before), `git reset --hard $baseline_sha` and set `exit_status=blocked_regression`. Do NOT enter Phase 4 on a regressing diff.

### Phase 4 — Unified Code Review

On the commit range `$baseline_sha..HEAD`, review holistically.

**A. Diff-internal hygiene (classic checks):**
- Any duplicate logic introduced across commits (same function rewritten in two places)?
- Test coverage gaps (fixed code without test)?
- Dead code / stray `console.log` / `print` debug lines?
- Cross-commit inconsistency (same file edited 3 times in this cycle)?
- Any commit message vague or missing finding id?

**B. Finding ↔ commit match (mandatory per-finding audit — do NOT skip).**

For EACH finding in `findings-after.json` with `status: "fixed"`, run these 4 sub-checks and record the verdict in `review.md`:

1. **fix_site_match** — compare the commit's changed files against the finding's `evidence.file:line` / `evidence.run_json` / `suggested_fix_path`. They MUST share a directory prefix. Examples of violations:
   - finding `evidence.file:line: orchestrator/backend/app/services/launcher.py:2704`, commit touches only `agent/.opencode/prompts/**.txt` → FAIL
   - finding `suggested_fix_path: orchestrator/frontend/src/components/progress/*.tsx`, commit touches only `orchestrator/backend/app/db.py` → FAIL
   - Reference: cycle `20260423T134501Z` commit `8aed200` passed classic review because checklist A never asked this question; this rule exists because of that failure.

2. **test_exercises_failure** — the commit must have added or modified a test that references the finding's specific failure mode in its assertion or setup. Examples of what counts:
   - `ui-07 STOP transition` fix → test must call `click STOP` or POST `/status stopped` and assert the transition
   - `queue_incomplete` classification fix → test must construct a mid-work container exit scenario
   - A test that only verifies the fix's BYPRODUCT (e.g. "rerender produces valid output" for a queue-classification finding) does NOT count.

3. **commit_msg_finding_id** — the commit message's `FND-XXX` token must match a finding id that exists in this cycle's `findings-before.json`. A commit that claims `FND-007` but findings-before only defines `FND-001..FND-003` → FAIL.

4. **re_run_source** — actually re-run the specific source that surfaced the finding, regardless of which category:
   - `orch_api` → `bash local-openclaw/scripts/audit_orchestrator_api.sh <cycle_id>`; the finding's API endpoint must now pass
   - `orch_log` → re-tail the log pattern that triggered; must no longer match
   - `orch_feature` → `python3 local-openclaw/scripts/audit_orchestrator_features.py <cycle_id>`
   - `orch_ui` → re-execute the specific `ui-XX` check in the browser toolset, save a screenshot, confirm `result: passed`
   - `agent_bug` (failed run) → fetch `GET /projects/<id>/runs` and confirm no run has that finding's same `stop_reason_code` in the last minute; OR fetch the run's updated `run.json` and confirm the specific inconsistency (stale `active_agents`, missing env key, etc.) is gone

**If ANY of B1–B4 fails for a finding that's currently `status: fixed`:** either (a) make one cleanup commit that addresses the gap, OR (b) change the finding's `status` from `fixed` back to `open` with `reason` documenting the gap, so the next cycle picks it up with elevated severity (persistent-bug rule).

**C. Cross-cycle regression delta (F2).** Before closing Phase 4, run:

```bash
python3 local-openclaw/scripts/check_regression_against_prior_cycles.py \
    <baseline_sha> --lookback 30
```

It lists lines this cycle's commits DELETED that were ADDED by recent `fix(audit-*)` commits. For every flagged line, you MUST either:
1. Include a brief justification in `review.md` under a `## Cross-cycle deletions` section — "removed because a newer finding supersedes it" or similar. The justification references the new finding that authorized the removal.
2. Restore the line via a cleanup commit and reopen the finding you thought you fixed.

You may NOT silently remove lines that prior audit commits added. That's how regressions like cycle `20260423T134501Z` commit `8aed200` happened — the re-render wiped a parallel_dispatch rule added by `badb8ef`, and classic review didn't notice.

Validator usage note: `validate_revert_evidence.py` expects the cycle id, not a findings file path. Use `python3 local-hermes-agent/scripts/validate_revert_evidence.py <cycle_id> --baseline-sha <baseline_sha>`; passing `local-hermes-agent/audit-reports/<cycle>/findings-after.json` makes it look for a nested audit directory and exits 2.

**Revert cooling-off (new, MANDATORY when F2 flags deletions).** Prose justification in `review.md` is necessary but NOT sufficient — without concrete data it lets the same rule flip-flop across cycles (parallel ↔ serialized consume-test was reverted 4 times in 21 hours between `badb8ef`/`ee824b9`/`8abdab7`/`5793ded` with no benchmark data supporting any direction).

When F2 flags deletions, every finding in `findings-after.json` whose fix commit is in the reverting cycle MUST carry `evidence.regression_evidence` with AT LEAST ONE of these concrete data points (dict or colon-separated string):

- `recall_drop_cycle: <cycle_id>` — benchmark-metrics-history.json cycle where the metric regressed (the F2 revert's actual measured effect)
- `failing_test: <path>:<line> — <short failure summary>` — a test that was passing and is now failing due to the prior fix
- `log_tail: <engagement_workspace>/log.md:<line> — <context>` — an engagement log entry showing the prior fix causing a concrete operational failure
- `case_outcome: cases.db case <id> marked ERROR — <short reason>` — a dispatcher outcome proving the prior fix broke a case

Prose-only entries ("parallel dispatch displaced serialized rule") do NOT satisfy this; the validator (`scripts/validate_revert_evidence.py`) rejects them. If you cannot supply concrete evidence, the finding MUST stay `deferred` with reason `"revert cooling-off: no concrete regression evidence this cycle"` — deferred findings carry to the next cycle, where the natural run will produce the data.

**D. Adversarial review (F3).** After finishing review.md, write a SECOND file `audit-reports/<cycle_id>/adversarial-review.md` from a distinct "fresh reviewer" perspective. Rules for this file:

1. **Context isolation.** Do not reference your Phase 2 reasoning (why you chose to edit a particular file, which hypothesis you tested). The adversarial reviewer only sees:
   - `findings-before.json` (the bugs)
   - `git diff <baseline_sha>..HEAD` (the proposed fixes)
   - The source tree at HEAD

2. **For each finding (regardless of current status)**, answer three yes/no questions independently:
   - Q1: Does the diff plausibly prevent this finding's exact failure mode from reproducing? Show your reasoning by pointing at a specific hunk + explaining the causal chain from "user/test does X" to "X now succeeds".
   - Q2: Can you construct a scenario where the finding's failure still reproduces despite the diff? If yes, describe it concretely. If no, say why the diff is sufficient.
   - Q3: Does the diff introduce any NEW path that could fail the original check? (e.g., a new state where `_reconcile_run_status` flips back to running)

3. **If adversarial-review.md answers differ from review.md verdicts** (e.g., review.md says "FND-002 fixed", adversarial says "Q2: yes, scenario X reproduces"), treat the adversarial verdict as authoritative:
   - Either make a cleanup commit addressing the scenario, OR
   - Change the finding's status from `fixed` to `open` in findings-after.json with the scenario documented in `reason`.

4. **Do not self-ratify.** If both reviews agree on everything, that's fine, but the adversarial file must still exist and contain the full Q1/Q2/Q3 matrix per finding, not a one-line "all good".

This is the imperfect-but-cheap substitute for actually dispatching a separate sub-session. When context isolation becomes infrastructure-cheap (e.g., via a dedicated `adversarial-reviewer` subagent), the skill will call that directly.

**`review.md` MUST include the per-finding matrix.** Format:
```
## Finding ↔ commit match

| id | fingerprint | fix_site | test_exercises | commit_msg_id | re_run | verdict |
|----|-------------|----------|----------------|---------------|--------|---------|
| FND-001 | orch_api-69c2fa34 | ✅ launcher.py | ✅ test_terminal_state | ✅ | ✅ passed | clean |
| FND-002 | orch_ui-3d82f700 | ❌ touched prompts only | ❌ test unrelated | ✅ | ❌ ui-07 still fails | REOPENED |
```

Always write the review conclusion to `audit-reports/<cycle_id>/review.md` (whether or not cleanup commits were needed — the Discord summary pulls from this file). If issues were found, also make 1-2 small cleanup commits OR reopen the affected finding(s).

## Hard Rules (read before every cycle)

**Never** create new orchestrator runs during audit — not via UI, not via `POST /projects/{id}/runs`, not via `create_runs.sh`. The auditor is read-only over existing run history. To exercise UI controls that need a live run, pick the most recent non-initial run from `latest-runs.json`.

**Never** brute-force the login form. Token injection via localStorage is the only supported path (see §6 orch_ui). If the token is rejected, record `token_invalid` and skip UI work.

**Cycle budget**: 50 min wall clock AND ~300 tool-call turns. Flush state AS YOU GO:
- Update `source-status.json` after each source finishes its scan (not after Phase 1 ends).
- Append findings to `findings-before.json` as you discover them; re-rank at Phase 1 end.
- Update `findings-after.json` status fields after each fix commit.
- Watch your tool-call count: browser navigation + DOM reads + screenshots can consume 20-30 calls per UI check. If you're past turn 200 and still in Phase 1, stop and flush before doing another check.
- When writing small Python checkpoint helpers across the controller's macOS Python versions, prefer `datetime.datetime.now(datetime.timezone.utc)` over `datetime.datetime.now(datetime.UTC)`; older local Python builds may not expose `datetime.UTC` and will crash after partially writing artifacts.

## Hard Limits

- Max 8 fix commits + max 2 review cleanup commits = 10 per cycle total
- Each commit MUST pass its local test before landing
- Regression → full reset (`git reset --hard baseline_sha`)
- Stuck on single finding (3 verify failures) → skip + mark `manual_review_needed`
- Cycle hard-timeout: 50 minutes total wall clock (was 20 — the UI walk alone needs ~15)

## Exit Status Codes (written into auditor-state.json)

- `ok` — findings reduced, no regression, cycle complete
- `ok_no_fixes` — no findings found (healthy)
- `blocked_regression` — regression detected, rolled back to baseline
- `stuck` — all top-N findings required manual_review_needed
- `orchestrator_down` — prep couldn't reach `http://127.0.0.1:18000`
- `hermes_timeout` — Hermes agent exceeded 20min

## Reporting

When the cycle finishes, print the final summary **in English**. Include:

1. Cycle ID and baseline SHA
2. Phase 1 finding counts by category and severity
3. Phase 2: which findings were fixed, which were skipped
4. Phase 3: fixed_count, regression_count
5. Phase 4: code review findings and cleanup commits (if any)
6. Final exit_status

## Commit Rule

Each confirmed fix gets its own commit: `fix(audit-<category>): <FND-id> <root_cause_short>` followed by a 2-3 line body (reproducer + file:line + post-fix evidence). See Phase 2 step 4 for the rationale; empty bodies are forbidden.

Cleanup commits from Phase 4: `chore(audit-review): <description>` PLUS a 2+ line body explaining what the cleanup is and why (which finding/review note authorized it, what was removed/changed, what verifies the cleanup is safe). Meta-audit on 2026-04-28 caught a 1-line `chore(audit-review)` slipping through (`abbac6b`) — the original "body required only if non-trivial" carve-out was abused, so the rule is now uniform: every audit-namespace commit (`fix(audit-*)`, `chore(audit-review)`, `chore(audit-*)`) needs a non-empty body.

If the verified fix lives under `local-openclaw/`, remember that path is gitignored in this repo. Stage those files with `git add -f ...` before running `git diff --check` / `git commit`, otherwise the cycle can appear clean while the actual auditor fix is still unstaged.

Do not push.

## Orchestrator Lifecycle

When verification requires restarting the local orchestrator, use:
- `./orchestrator/run.sh`
- `./orchestrator/stop.sh`

For changes affecting the orchestrator/runtime image:
```bash
./orchestrator/run.sh --rebuild
```

When creating a fresh local run for verification:
```bash
FORCE_REPLACE_ACTIVE_RUNS=1 TARGET_FILTER=local local-openclaw/scripts/create_runs.sh
```

**NEVER run `docker restart juice-shop` yourself.** The cycle controller handles Juice Shop restart exclusively in the post-cycle step to preserve challenge score data.
