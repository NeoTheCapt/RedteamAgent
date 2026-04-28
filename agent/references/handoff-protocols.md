# Agent Handoff Protocols

How each subagent's output flows back through the operator under the streaming
pipeline. Stage transitions are the canonical interface — every case-batch
subagent emits a `### Case Outcomes` block whose `DONE STAGE=<stage>` lines the
operator translates into `dispatcher.sh ... done <id> --stage <stage>`.

The two subagent classes:
- **case-batch** (source-analyzer, vulnerability-analyst, fuzzer, exploit-developer):
  dispatched via `fetch-by-stage <stage> <type> <limit> <agent>`; must return
  a `### Case Outcomes` section accounting for every fetched case ID.
- **non-batch** (recon-specialist, osint-analyzer, report-writer): no case-batch
  contract. Triggered by lifecycle events (engagement start, respawn flags,
  end-of-cycle) and write to artifacts directly.

See `agent/operator-core.md` for the canonical stage list and `Rule 6` hygiene.

---

## RECON-SPECIALIST → operator → cases.db / surfaces / intel

**Trigger**: engagement start (parallel with source-analyzer); re-dispatch when
`auth_respawn_check.sh` writes `.auth-respawn-required`.

**Outputs**: endpoint list, technologies, JS file URLs, parameter inventory,
optional Surface Candidates and findings.

**Operator does**:
1. Endpoints → `./scripts/recon_ingest.sh` (lands them in cases.db at
   `stage=ingested`); the source-analyzer / vulnerability-analyst dispatch
   loop picks them up by type.
2. Technology stack → findings.md (INFO) + intel.md Technology table.
3. `#### Surface Candidates` block → JSONL via
   `./scripts/append_surface_jsonl.sh "$DIR"`.
4. Obvious vulns (default creds, open admin) → write the finding via
   `append_finding.sh`, then dispatch exploit-developer ad-hoc on that case.

---

## SOURCE-ANALYZER → operator → queue / surfaces / findings

**Trigger**: `fetch-by-stage ingested <type> <limit> source-analyzer` for
`type ∈ {javascript, page, stylesheet, data, unknown, api-spec}`. The operator
runs `prune_vendor_cases.py` BEFORE every javascript fetch (see
`operator-core.md` Rule 6) so vendor noise never lands here.

**Outputs**: API endpoints extracted, frontend routes, secrets/tokens, hidden
paths, source maps, Surface Candidates, plus the mandatory `### Case Outcomes`.

**Stage emissions**:
- `DONE STAGE=source_analyzed` — artifact yielded follow-up cases or surfaces.
  The case is terminal as a *source*; new follow-up cases land at
  `stage=ingested` for v-analyst / source-analyzer.
- `DONE STAGE=vuln_confirmed` — rare; the source itself contains a directly
  testable vuln (bundled secret + reachable API). Goes to exploit-developer
  next.
- `DONE STAGE=clean` — third-party / non-actionable artifact.
- `REQUEUE` / `ERROR` — partial work still owed / irrecoverable.

**Operator does**:
1. Apply each `DONE STAGE=<stage>` via `dispatcher.sh ... done <id> --stage`.
2. Ingest emitted follow-up cases (`./scripts/dispatcher.sh ... requeue` or a
   second `recon_ingest.sh` import).
3. Surface Candidates → `append_surface_jsonl.sh`.
4. Secrets/tokens → findings.md immediately (HIGH/MEDIUM) +
   `intel-secrets.json` for full values; intel.md Credentials table holds the
   preview only.

---

## VULNERABILITY-ANALYST → operator → exploit-developer / fuzzer

**Trigger**: `fetch-by-stage ingested <type> <limit> vulnerability-analyst` for
`type ∈ {api, form, graphql, upload, websocket}`.

**Outputs**: bounded triage probes (1–2 per family) across the wide attack
family list (see v-analyst `SKILLS` — broader than exploit-developer by design),
plus findings for confirmed signal and the mandatory `### Case Outcomes`.

**Stage emissions**:
- `DONE STAGE=vuln_confirmed` — concrete exploit-relevant signal; case advances
  to exploit-developer.
- `DONE STAGE=fuzz_pending` — endpoint warrants deep fuzz that doesn't fit in
  the inline ≤500-entry budget (param-name discovery on burp-parameter-names,
  raft-medium/large directory enum, credential spraying ≥1k, vhost top-1M);
  case advances to fuzzer.
- `DONE STAGE=api_tested` — bounded coverage saw no signal. Terminal.
- `DONE STAGE=clean` — structurally non-attackable. Terminal.
- `REQUEUE` (often paired with a `REQUEUE_CANDIDATE` note naming the unsampled
  higher-risk family) / `ERROR`.

**Operator does**:
1. Apply stage transitions via `dispatcher.sh done`.
2. Confirmed findings → ensure they're already in findings.md (v-analyst
   appends via `append_finding.sh`); if a result names a finding ID without
   appending, format it and append.
3. `vuln_confirmed` cases will be picked up by the next
   `fetch-by-stage vuln_confirmed ... exploit-developer`.
4. `fuzz_pending` cases will be picked up by the next
   `fetch-by-stage fuzz_pending ... fuzzer`.

---

## FUZZER → operator → vulnerability-analyst chain / queue

**Trigger**: `fetch-by-stage fuzz_pending <type> <limit> fuzzer`. (Ad-hoc
manual `/scan` dispatches and exploit-developer chain support skip the
case-batch contract.)

**Outputs**: discovered paths, valid parameters, anomalous responses, plus
the mandatory `### Case Outcomes` for case-batch dispatches.

**Stage emissions**:
- `DONE STAGE=vuln_confirmed` — fuzz turned up an exploitable parameter /
  hidden path / valid credential.
- `DONE STAGE=api_tested` — wordlist exhausted, no above-baseline anomaly.
  Terminal.
- `DONE STAGE=clean` — structurally non-fuzzable. Terminal.
- `REQUEUE` / `ERROR`.

**Operator does**:
1. Apply stage transitions.
2. New paths/endpoints discovered → ingest as new cases at `stage=ingested`
   (the natural type-router will hand them back to v-analyst or source-analyzer).
3. Confirmed valid credentials → write to auth.json + trigger the credential
   auto-use flow (see `operator-core.md` Credential Auto-Use).

---

## EXPLOIT-DEVELOPER → operator → findings / auth.json / queue

**Trigger**: `fetch-by-stage vuln_confirmed <type> <limit> exploit-developer`,
plus ad-hoc dispatches for chain analysis, full-findings reviews, or
credential validation in the auth-respawn flow.

**Outputs**: CONFIRMED / PARTIAL / FAILED status with PoC, extracted data,
chain analysis, severity reassessment. Case-batch runs end with `### Case
Outcomes`; non-batch runs use the `### Exploitation Results` block.

**Stage emissions** (case-batch only):
- `DONE STAGE=exploited` — finding written; terminal.
- `DONE STAGE=clean` — exploitation failed and no chain candidate; terminal.
- `DONE STAGE=vuln_confirmed` — rare; partial exploit needs a future-step
  artifact and should re-enter the exploit queue later.
- `REQUEUE` (back to v-analyst for follow-up triage) / `ERROR`.

**Operator does**:
1. Apply stage transitions.
2. CONFIRMED + credentials → update auth.json on the canonical schema; the
   next `auth_respawn_check.sh` tick will write `.auth-respawn-required` and
   the operator re-dispatches recon-specialist + source-analyzer with the
   auth context. Also dispatch a bounded auth-validation exploit-developer
   pass in the SAME turn (see `operator-core.md`).
3. CONFIRMED + new attack surface → ingest new cases at `stage=ingested`.
4. PARTIAL → record as MEDIUM, consider scheduling a follow-up fuzz via
   `STAGE=fuzz_pending` if depth is needed.
5. FAILED → log.md note, move on.

---

## OSINT-ANALYST → operator → intel.md / findings

**Trigger**: `intel_changed_check.sh` writes `.osint-respawn-required` after
intel.md's filled-row count grows. The operator dispatches osint-analyst with
a pointer to that flag file. (Engagement start does NOT auto-dispatch
osint-analyst — there's no intel for it to enrich until something else writes
to intel.md first.)

**Outputs**: writes intel.md ONLY (never findings.md directly). Returns an
Intelligence Assessment block with prioritized correlations.

**Operator does** after osint-analyst returns:
1. Read the Intelligence Assessment.
2. HIGH-value CVE + PoC match → write a finding via `append_finding.sh`, then
   dispatch exploit-developer ad-hoc on the matching case/endpoint.
3. Breached credentials → write a finding + dispatch exploit-developer for
   credential validation.
4. Historical endpoints (Wayback / cert-transparency hits in scope) → ingest
   as new cases at `stage=ingested`.
5. MEDIUM/LOW → record as INFO in findings.md.
6. Clear `.osint-respawn-required` after dispatch so the next intel.md change
   re-arms the trigger.

---

## REPORT-WRITER ← operator provides

**Trigger**: end-of-cycle (active stages drained, surface coverage passes, no
in-flight subagent), or interim snapshot via
`./scripts/compose_partial_report.sh "$DIR"` (zero-token, no subagent dispatch).

**Operator provides**: the engagement directory containing scope.json, log.md,
findings.md, intel.md, cases.db, intel-secrets.json, auth.json.

**Operator does** after report-writer returns:
1. `rm -f "$DIR/report.md.partial"` to clear the interim-stub marker.
2. `./scripts/finalize_engagement.sh "$DIR"` (the ONLY allowed
   report-finalization command — never `jq`-mutate scope.json directly).

---

## Mechanical Respawn Flags (per-tick checks)

Both flags are written by idempotent high-water-mark checks; the operator runs
them every tick (see `operator-core.md`).

| Flag file | Writer | Operator action |
|---|---|---|
| `.auth-respawn-required` | `auth_respawn_check.sh` (when `validated_credentials.length` increases) | Re-dispatch recon-specialist + source-analyzer with auth context, then `rm` the flag. |
| `.osint-respawn-required` | `intel_changed_check.sh` (when intel.md filled-row count rises above the high-water mark) | Dispatch osint-analyst to correlate the new intel, then `rm` the flag. |

Without these flags, ghost-subagent regressions return: agent runs landed creds
in 30% of cycles but only re-recon'd in <10%, and osint-analyst was at 0
dispatches across observed engagements before the intel flag existed.

---

## Wildcard Mode Specifics

- DUAL FINDING WRITE: every finding → child's findings.md + parent's
  findings.md.
- Parent prefix: `## [sub.domain.com / FINDING-XX-NNN] Title`.
- Set `ENGAGEMENT_DIR` to the specific child directory before each operation.
