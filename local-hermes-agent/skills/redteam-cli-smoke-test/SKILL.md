---
name: redteam-cli-smoke-test
description: "End-to-end smoke test of the CLI redteam agent: drives ./run.sh in redteam-agent-test-docker through `/autoengage <URL>`, waits for engagement completion, then sweeps console logs and engagement artifacts for bugs to judge whether the CLI runtime is healthy."
---

# RedTeam CLI Smoke Test

## Purpose

Run the dockerized CLI redteam agent end-to-end against a live target, then surface bugs by reading what actually happened. The goal is not to discover vulnerabilities in the target — it is to exercise the agent itself and tell whether:

1. The container boots, OpenCode picks up the persistent model config, and `/autoengage` is parsed
2. All five phases (recon → collect → consume-test → exploit → report) execute without fatal errors
3. The engagement reaches a real terminal state (`scope.json.current_phase=complete` or an explicit stop reason), not a silent hang
4. The console log is free of unhandled tracebacks, docker tool failures, and model-API errors
5. The engagement artifacts (`findings.md`, `surfaces.jsonl`, `cases.db`, `log.md`) are well-formed

Read-only by default — this skill diagnoses; it does not patch.

## When to Activate

- After any change to `agent/docker/redteam-allinone/{Dockerfile,run.sh.tpl}` or `install.sh` docker mode
- After bumping `opencode-ai` in the image
- After modifying operator prompts (`agent/operator-core.md`, `.opencode/prompts/agents/operator.txt`) or any consume-test contract
- Before a release tag
- When the user reports the CLI agent "stuck" / "doesn't finish" / "doesn't start"

Trigger phrases: "smoke test the cli", "run autoengage and check it", "test the docker agent end-to-end", "判断 cli 版 redteam agent 运行是否正常".

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `target_url` | `https://web3.okx.com` | URL passed to `/autoengage` |
| `test_dir` | `/Users/cis/dev/projects/redteam-agent-test-docker` | Has `run.sh`, `.env`, `workspace/`, `opencode-{home,config,state}/` |
| `console_log` | `$test_dir/last-run-console.log` | Captured stdout+stderr from the entire run |
| `wait_timeout_min` | `240` (4 hours) | Hard ceiling on how long to wait before declaring `runtime_error: timeout` |
| `poll_interval_sec` | `90` | How often to poll for terminal state (use `ScheduleWakeup` between polls) |

## Methodology

The skill runs six phases in order. Each writes to `$test_dir/last-run-smoke-report.md`. Don't skip phases — Phase B's launch arguments are read by Phase C's poll loop; Phase E uses Phase D's bug list.

### Phase A — Pre-flight

Goal: refuse to launch a smoke that's guaranteed to fail.

```bash
TEST_DIR="${TEST_DIR:-/Users/cis/dev/projects/redteam-agent-test-docker}"
cd "$TEST_DIR"

# A1: image present
docker image inspect redteam-allinone:latest >/dev/null 2>&1 \
  || { echo "FAIL A1: image missing — run install.sh docker first"; exit 2; }

# A2: model auth available — accept either .env API keys OR a populated
# opencode-home/auth.json (the canonical OpenCode location, written by
# `opencode auth login` and persisted across container restarts).
A2_PASS=0
A2_SOURCE=""
if grep -qE '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY)=.{8,}' .env 2>/dev/null; then
    A2_PASS=1; A2_SOURCE=".env"
fi
if [[ -s opencode-home/auth.json ]] \
   && jq -e 'keys | length > 0' opencode-home/auth.json >/dev/null 2>&1; then
    A2_PASS=1; A2_SOURCE="${A2_SOURCE:+$A2_SOURCE+}auth.json"
fi
[[ "$A2_PASS" == "1" ]] \
  || { echo "FAIL A2: no usable model auth in .env or opencode-home/auth.json"; exit 2; }
echo "✓ A2 model auth (source: $A2_SOURCE)"

# A3: model config persisted (avoid the prompt-on-every-start issue this skill
# was originally written to catch)
ls -la opencode-config/opencode/ 2>/dev/null | head
[[ -d opencode-config/opencode ]] && [[ -n "$(ls -A opencode-config/opencode 2>/dev/null)" ]] \
  || echo "WARN A3: opencode-config/opencode is empty — model selection may be re-prompted"

# A4: workspace + opencode dirs writable
for d in workspace opencode-home opencode-config opencode-state; do
  [[ -w "$d" ]] || { echo "FAIL A4: $d not writable"; exit 2; }
done

# A5: docker daemon up
docker info >/dev/null 2>&1 || { echo "FAIL A5: docker daemon not responding"; exit 2; }
```

If any FAIL fires, abort and write the verdict directly. Don't launch.

### Phase B — Launch

Goal: start the engagement non-interactively, capture every byte of console output.

```bash
TARGET_URL="${TARGET_URL:-https://web3.okx.com}"
CONSOLE_LOG="${CONSOLE_LOG:-$TEST_DIR/last-run-console.log}"
RUN_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_START_EPOCH="$(date +%s)"

# Stash the launch metadata so Phase C/F can read it.
cat > "$TEST_DIR/last-run-meta.json" <<EOF
{"target_url":"$TARGET_URL","start_iso":"$RUN_START_ISO","start_epoch":$RUN_START_EPOCH}
EOF

# Background a CONTINUATION LOOP. `opencode run "<msg>"` is single-prompt: it
# runs the operator agent for up to ~12 internal steps and exits at
# session.idle. /autoengage needs a multi-hour core loop, so a single
# `opencode run` call only reaches engage init + the first dispatch.
#
# To drive the engagement to terminal state we re-fire `opencode run
# --continue "continue"` between iterations; --continue resumes the same
# session via the persisted opencode.db (in opencode-home/, mounted), so
# the operator agent keeps its working memory across iterations.
#
# The loop exits when scope.json reaches complete, log.md records a
# stop_reason, or the wall-clock timeout expires. All console output (from
# every iteration) is concatenated into the same log file.
cd "$TEST_DIR"
WAIT_TIMEOUT_SEC=$(( ${WAIT_TIMEOUT_MIN:-240} * 60 ))
nohup bash -c '
    set -u
    TEST_DIR="'"$TEST_DIR"'"
    TARGET_URL="'"$TARGET_URL"'"
    CONSOLE_LOG="'"$CONSOLE_LOG"'"
    START_EPOCH='"$RUN_START_EPOCH"'
    TIMEOUT_SEC='"$WAIT_TIMEOUT_SEC"'
    cd "$TEST_DIR"

    is_terminal() {
        # Use eng_-prefixed names: $status is sometimes readonly in the
        # harness shell that hosts run_in_background, and `local status`
        # then dies with "read-only variable".
        local eng eng_status eng_phase elapsed
        eng="$(find workspace/engagements -maxdepth 1 -mindepth 1 -type d \
               -newermt "@$START_EPOCH" 2>/dev/null | sort | tail -1)"
        if [[ -n "$eng" && -f "$eng/scope.json" ]]; then
            eng_status="$(jq -r ".status // \"\"" "$eng/scope.json" 2>/dev/null)"
            eng_phase="$(jq -r ".current_phase // \"\"" "$eng/scope.json" 2>/dev/null)"
            [[ "$eng_status" == "complete" && "$eng_phase" == "complete" ]] && return 0
        fi
        if [[ -n "$eng" && -f "$eng/log.md" ]] \
           && grep -qE "Run stop.*stop_reason=" "$eng/log.md"; then
            return 0
        fi
        elapsed=$(( $(date +%s) - START_EPOCH ))
        (( elapsed > TIMEOUT_SEC )) && return 0
        return 1
    }

    iter=0
    printf "[smoke loop] iter=0 starting /autoengage %s\n" "$TARGET_URL" >>"$CONSOLE_LOG"
    ./run.sh -- opencode run --print-logs --log-level INFO \
        --dangerously-skip-permissions --agent operator \
        "/autoengage $TARGET_URL" >>"$CONSOLE_LOG" 2>&1
    while ! is_terminal; do
        iter=$((iter+1))
        printf "[smoke loop] iter=%d --continue\n" "$iter" >>"$CONSOLE_LOG"
        ./run.sh -- opencode run --print-logs --log-level INFO \
            --dangerously-skip-permissions --agent operator --continue \
            "continue the engagement core loop until scope.json is complete or you hit a stop reason" \
            >>"$CONSOLE_LOG" 2>&1
        sleep 3
    done
    printf "[smoke loop] terminal reached at iter=%d\n" "$iter" >>"$CONSOLE_LOG"
' </dev/null >/dev/null 2>&1 &
RUN_PID=$!
echo "$RUN_PID" > "$TEST_DIR/last-run.pid"
disown
echo "smoke loop launched: pid=$RUN_PID target=$TARGET_URL log=$CONSOLE_LOG"
```

If the `nohup ... &` returns immediately without a sane PID, that is itself a failure (write `runtime_error: launch_failed` and skip to Phase F).

The loop wrapper (one bash background process) outlives any individual
`opencode run` invocation, so the smoke survives the per-iteration session
exit at step 12. Phase C still polls the same scope.json / log.md fields —
nothing else changes, only the launch path.

### Phase C — Wait for terminal state

Goal: block until the engagement reaches a terminal state, but bound by `wait_timeout_min`.

Terminal states are (in priority order):
1. `scope.json.status == "complete"` AND `scope.json.current_phase == "complete"` → `completed`
2. `log.md` contains `Run stop` with `stop_reason=…` → that stop reason
3. The `RUN_PID` exited with non-zero before any engagement was created → `runtime_error: container_died`
4. Wall clock exceeded `wait_timeout_min` → `runtime_error: timeout`

Poll loop pattern (operator runs this between `ScheduleWakeup` calls so the conversation context isn't blocked):

```bash
TEST_DIR="${TEST_DIR:-/Users/cis/dev/projects/redteam-agent-test-docker}"
RUN_PID="$(cat "$TEST_DIR/last-run.pid" 2>/dev/null)"
START_EPOCH="$(jq -r .start_epoch "$TEST_DIR/last-run-meta.json")"
TIMEOUT_SEC=$(( ${WAIT_TIMEOUT_MIN:-240} * 60 ))
NOW=$(date +%s)
ELAPSED=$(( NOW - START_EPOCH ))

# Find the most-recent engagement created by THIS run. Engagement timestamps
# are second-resolution; filter by start_epoch to avoid touching prior runs'
# leftover dirs.
ENG="$(find "$TEST_DIR/workspace/engagements" -maxdepth 1 -mindepth 1 -type d \
       -newermt "@$START_EPOCH" 2>/dev/null | sort | tail -1)"

# Terminal check 1: scope.json complete
if [[ -n "$ENG" && -f "$ENG/scope.json" ]]; then
  STATUS=$(jq -r '.status // ""' "$ENG/scope.json" 2>/dev/null)
  PHASE=$(jq -r '.current_phase // ""' "$ENG/scope.json" 2>/dev/null)
  if [[ "$STATUS" == "complete" && "$PHASE" == "complete" ]]; then
    echo "TERMINAL: completed (eng=$ENG elapsed=${ELAPSED}s)"
    exit 0
  fi
fi

# Terminal check 2: explicit stop reason in log.md
if [[ -n "$ENG" && -f "$ENG/log.md" ]]; then
  STOP_LINE=$(grep -E 'Run stop.*stop_reason=' "$ENG/log.md" | tail -1)
  if [[ -n "$STOP_LINE" ]]; then
    echo "TERMINAL: $STOP_LINE"
    exit 0
  fi
fi

# Terminal check 3: container died without producing an engagement
if [[ -n "$RUN_PID" ]] && ! kill -0 "$RUN_PID" 2>/dev/null; then
  if [[ -z "$ENG" ]]; then
    echo "TERMINAL: container_died (no engagement created, pid $RUN_PID gone)"
    exit 0
  fi
  # Container died but engagement exists — Phase E will judge it
  echo "TERMINAL: container_died_post_launch (eng=$ENG)"
  exit 0
fi

# Terminal check 4: timeout
if (( ELAPSED > TIMEOUT_SEC )); then
  echo "TERMINAL: timeout (elapsed=${ELAPSED}s > ${TIMEOUT_SEC}s)"
  exit 0
fi

echo "still running: elapsed=${ELAPSED}s eng=${ENG:-<none yet>} pid=$RUN_PID"
exit 1
```

Operator behaviour: when the poll script exits 1, schedule a wakeup `${POLL_INTERVAL_SEC}s` later (default 90s). When it exits 0, advance to Phase D. The poll script must NOT block — it returns immediately each call.

### Phase D — Console-log analysis

Goal: scan `$CONSOLE_LOG` for known bug signatures.

```bash
CONSOLE_LOG="${CONSOLE_LOG:-$TEST_DIR/last-run-console.log}"

# Helper: opencode logs every permission evaluation as one giant line that
# embeds the agent's intended bash/grep argument verbatim — including
# literal "ERROR", "ratelimit", "kong", etc. Counting raw matches against
# those lines produced 4+10 false positives in the 2026-04-28 web3.okx.com
# smoke. Exclude permission-evaluator lines AND the agent's own python
# print(f'…') / `out[..]=[f'ERROR: …']` literals up front.
DENOISED="$(sed -E \
    -e '/^INFO.*service=permission/d' \
    -e '/print\(f.*ERROR/d' \
    -e "/=\\[f'ERROR/d" \
    "$CONSOLE_LOG")"

# D1: Python tracebacks (orchestrator/launcher/dispatcher errors)
TRACEBACKS=$(printf '%s\n' "$DENOISED" | grep -cE '^Traceback \(most recent call last\)')

# D2: ERROR/FATAL log lines (excluding routine `error_count: 0` JSON noise)
ERR_FATAL=$(printf '%s\n' "$DENOISED" | grep -cE '\b(ERROR|FATAL)\b' \
            | grep -vE 'error_count":\s*0|errors":\s*\[\]')

# D3: docker-tool failures (run_tool returns non-zero, container exited)
DOCKER_FAILS=$(printf '%s\n' "$DENOISED" | grep -cE 'docker:.*Error|docker (run|exec) .* exited|run_tool.*exit code [^0]')

# D4: model API errors (rate limit, auth, provider down).
# Anchor to opencode/server emit lines so agent grep arguments containing
# the same words don't false-positive (e.g., agent shell `grep ratelimit`
# on the target's own kong/k8s logs).
MODEL_API_ERR=$(printf '%s\n' "$DENOISED" \
    | grep -E '^(INFO|WARN|ERROR)' \
    | grep -cE 'rate.?limit(ed|_exceeded)?|invalid_api_key|401 Unauthorized\b|503 Service Unavailable\b|model_not_found')

# D5: subagent dispatch failures (operator sent task() but child errored)
DISPATCH_FAILS=$(printf '%s\n' "$DENOISED" | grep -cE 'subagent.*error|task\(\).*failed|agent did not return')

# D6: queue stalls / orphaned cases. Note: queue_incomplete by itself is
# now a legitimate stop_reason emitted by the operator when an unauthenticated
# run hits a wallet-gated endpoint — only count it as a STALL when it
# appears outside the operator's explicit stop announcement (either
# `stop_reason=…` log entry, or a `[operator] Stop reason: …` console
# echo of the same).
QUEUE_STALL=$(printf '%s\n' "$DENOISED" \
    | grep -E 'incomplete_stop|queue_incomplete|queue_stalled|orphan(ed)? processing' \
    | grep -vE 'stop_reason=|\[operator\] Stop reason:' \
    | wc -l | tr -d ' ')

# D7: missing-script warnings (rename loss like run_context_snapshot.py 2026-04-27)
MISSING_SCRIPT=$(printf '%s\n' "$DENOISED" | grep -cE 'warning: missing .*\.py|warning: missing .*\.sh|No such file or directory.*scripts/')

# D8: model reconfiguration prompt (the bug this skill exists to catch)
MODEL_PROMPT=$(printf '%s\n' "$DENOISED" | grep -cE 'select.*provider|configure.*model|choose a model')

# Summarize
cat <<EOF
D1 tracebacks:        $TRACEBACKS
D2 ERROR/FATAL:       $ERR_FATAL
D3 docker tool fails: $DOCKER_FAILS
D4 model API errors:  $MODEL_API_ERR
D5 dispatch fails:    $DISPATCH_FAILS
D6 queue stalls:      $QUEUE_STALL
D7 missing scripts:   $MISSING_SCRIPT
D8 model re-prompts:  $MODEL_PROMPT
EOF

# For any non-zero count, save the first 5 matching lines as evidence:
for sig in 'Traceback' 'ERROR\b' 'docker.*Error' 'rate.?limit' 'subagent.*error' \
           'incomplete_stop' 'warning: missing' 'select.*provider'; do
  matches=$(grep -nE "$sig" "$CONSOLE_LOG" | head -5)
  [[ -n "$matches" ]] && echo "=== $sig ===" && echo "$matches"
done
```

Severity mapping for the verdict:
- **D1 (tracebacks) ≥ 1**: HIGH — uncaught exception
- **D3 (docker fails) ≥ 1**: HIGH — pentest-tool path broken
- **D4 (model API errors) ≥ 3**: HIGH — recurring auth/rate problem; isolated 1-2 may be transient
- **D6 (queue stalls) ≥ 1**: HIGH — pipeline contract regression
- **D7 (missing scripts) ≥ 1**: HIGH — rename loss recurrence (this skill's Phase E was extended on 2026-04-27 specifically for this)
- **D8 (model re-prompts) ≥ 1**: MEDIUM — XDG config-dir mount regression
- D2/D5: cumulative: ≤2 LOW (transient), ≥3 MEDIUM (real signal)

### Phase E — Engagement-artifact analysis

Goal: judge whether the engagement actually did something useful, not just exited cleanly.

```bash
ENG="$(find "$TEST_DIR/workspace/engagements" -maxdepth 1 -mindepth 1 -type d \
       -newermt "@$START_EPOCH" 2>/dev/null | sort | tail -1)"

# E1: phases reached
PHASES=$(jq -r '.phases_completed // [] | join(",")' "$ENG/scope.json" 2>/dev/null)
PHASE_NOW=$(jq -r '.current_phase // ""' "$ENG/scope.json" 2>/dev/null)
STATUS=$(jq -r '.status // ""' "$ENG/scope.json" 2>/dev/null)

# E2: findings
FINDINGS_TOTAL=$(grep -cE '^## \[FINDING-' "$ENG/findings.md" 2>/dev/null || echo 0)
FINDINGS_BY_AGENT=$(grep -oE 'FINDING-[A-Z]{2}' "$ENG/findings.md" 2>/dev/null | sort | uniq -c)

# E3: case queue end-state — pending or processing rows that survived
QUEUE_REMAINING=$(sqlite3 "$ENG/cases.db" \
  "SELECT status, COUNT(*) FROM cases GROUP BY status ORDER BY status;" 2>/dev/null)
QUEUE_PENDING=$(sqlite3 "$ENG/cases.db" \
  "SELECT COUNT(*) FROM cases WHERE status IN ('pending','processing');" 2>/dev/null)

# E4: surface coverage
SURFACE_TOTAL=$(wc -l < "$ENG/surfaces.jsonl" 2>/dev/null | tr -d ' ')
SURFACE_UNRESOLVED=$(jq -s 'map(select(.status != "covered" and .status != "not_applicable")) | length' \
  "$ENG/surfaces.jsonl" 2>/dev/null)

# E5: report
REPORT_LINES=$(wc -l < "$ENG/report.md" 2>/dev/null | tr -d ' ')

# E6: log.md final entry
LAST_LOG=$(tail -3 "$ENG/log.md" 2>/dev/null)

cat <<EOF
E1 phases:           completed=[$PHASES] current=$PHASE_NOW status=$STATUS
E2 findings:         total=$FINDINGS_TOTAL by_agent=$(echo $FINDINGS_BY_AGENT | tr '\n' ' ')
E3 queue end:        $(echo "$QUEUE_REMAINING" | tr '\n' ' ') pending+processing=$QUEUE_PENDING
E4 surfaces:         total=$SURFACE_TOTAL unresolved=$SURFACE_UNRESOLVED
E5 report.md:        $REPORT_LINES lines
E6 last log.md:      $LAST_LOG
EOF
```

Severity mapping:
- **E1 status != "complete"**: HIGH — engagement did not finish cleanly
- **E1 phases_completed missing `recon`/`collect`/`consume_test`/`exploit`/`report`**: HIGH — short-circuited
- **E2 FINDINGS_TOTAL == 0** for a non-trivial target like web3.okx.com: MEDIUM — possible quality regression. Allow 0 if scope.json shows recon/collect were skipped (e.g., target unreachable).
- **E3 QUEUE_PENDING > 0** at terminal state: HIGH — pipeline left work undone
- **E4 SURFACE_UNRESOLVED > 0** at terminal state with status=complete: HIGH — coverage gate bypassed
- **E5 REPORT_LINES == 0** but status=complete: HIGH — finalize script lied about completion

### Phase F — Verdict

Compose a single-line verdict + bug list at `$TEST_DIR/last-run-smoke-report.md`.

```markdown
# CLI Smoke Test Report — <ISO timestamp>

**Target**: <target_url>
**Engagement**: <ENG path>
**Wall time**: <Hh Mm Ss>
**Terminal state**: <completed | runtime_error: code | stop_reason=code>
**Verdict**: ✓ PASS  |  ⚠ PASS-WITH-WARNINGS  |  ✗ FAIL

## Phase D — Console signal counts
| Signal | Count | Severity |
|---|---|---|
| Tracebacks | N | HIGH if ≥1 |
| ERROR/FATAL | N | LOW≤2 / MEDIUM≥3 |
| Docker tool fails | N | HIGH if ≥1 |
| Model API errors | N | HIGH if ≥3 |
| Subagent dispatch fails | N | LOW≤2 / MEDIUM≥3 |
| Queue stalls | N | HIGH if ≥1 |
| Missing scripts | N | HIGH if ≥1 |
| Model re-prompts | N | MEDIUM if ≥1 |

## Phase E — Engagement signals
- Phases completed: [...]
- Findings: N total (VA: N, EX: N, SA: N, RE: N, OS: N, FZ: N)
- Queue end: pending=N processing=N done=N
- Surfaces: total=N unresolved=N
- Report: N lines

## Bugs found (severity-sorted)
1. [HIGH/MEDIUM/LOW] <short description> — evidence: <file:line or count>
2. ...

## Recommendation
- if PASS: cleared for release / further use
- if PASS-WITH-WARNINGS: ship with mitigations / open issues for warnings
- if FAIL: do not ship. Top 1-3 follow-up actions, each citing concrete file:line
```

Verdict rules:
- **FAIL**: any HIGH-severity bug present, or `Terminal state` is `runtime_error: timeout` / `container_died`
- **PASS-WITH-WARNINGS**: only MEDIUM/LOW bugs, OR `stop_reason=manual_stop`/`completed` with surface-coverage warnings
- **PASS**: terminal state is `completed`, zero HIGH severity, ≤1 MEDIUM, status=complete + non-empty report.md

## Output Format

Always write the report to `$TEST_DIR/last-run-smoke-report.md` so the next smoke run can `git diff` against it (regression detection across smoke runs).

The skill also touches `$TEST_DIR/last-run-meta.json`, `$TEST_DIR/last-run.pid`, and `$TEST_DIR/last-run-console.log` — these are intentionally outside the project repo (`redteam-agent-test-docker` is a sibling dir) so they don't pollute git.

## Execution Rules

1. **Background launch only**. Phase B uses `nohup ... &` because `/autoengage` runs for hours. The skill's poll loop (Phase C) returns immediately and is intended to be wrapped in `ScheduleWakeup` cycles by the operator. Never `wait` synchronously inside a single bash invocation — that breaks the operator's conversation context.
2. **Poll cadence**: 90s default. Don't drop below 60s (cache-warm window) or above 1800s (loses signal granularity).
3. **Cumulative log only**. Don't truncate `last-run-console.log` between phases — Phase D needs to see everything from launch through completion.
4. **Don't kill on first symptom**. Even if Phase D sees a traceback at minute 5, let the run reach a terminal state — the failure mode itself is data (e.g., "tracebacks at minute 5 but engagement still completed at minute 47" is HIGH but a different bug class than "container died at minute 5").
5. **Authorization sanity**: the test target (`https://web3.okx.com`) is a CTF/lab mirror per the project's `CLAUDE.md` AUTHORIZATION block. Do not change the target to a live third-party prod system.
6. **Read-only Phase D/E**. The smoke skill never writes inside `$ENG/` — it only reads `scope.json`, `log.md`, `findings.md`, `surfaces.jsonl`, `cases.db`. If a fix is needed, that's a separate skill / commit.

## Anti-patterns

- ❌ Running `./run.sh` interactively in the foreground and then trying to `wait` for it — the operator's TUI hangs.
- ❌ Killing the smoke run after the first traceback. Tracebacks before terminal state are evidence; killing them turns them into ambiguous noise.
- ❌ Re-using a stale `last-run-console.log` from a prior smoke. Always overwrite at Phase B.
- ❌ Asserting "no findings = bug" without checking whether the target was reachable. If recon couldn't reach the target, finding count is meaningless. The phases_completed list disambiguates.
- ❌ Using `docker exec` against an already-running container to invoke `opencode run` — Phase B's flow assumes a fresh container per smoke. Re-using state contaminates subsequent runs.
- ❌ Treating a `manual_stop` as a smoke failure when the user intentionally stopped the run. Distinguish by the log line text.
