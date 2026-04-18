# Agent Handoff Protocols

Detailed rules for how each agent's output flows to the next through the operator.

## RECON-SPECIALIST → next agents

recon outputs: endpoint list, technologies, JS file URLs, parameters

Operator does:
1. Pass JS file URLs → dispatch source-analyzer
2. Import ALL endpoints → `recon_ingest.sh` → cases.db
3. Record technology stack → findings.md (INFO severity) + intel.md
4. If obvious vulns found (default creds, open admin) → dispatch exploit-developer directly

## SOURCE-ANALYZER → queue + findings

source outputs: new API endpoints, routes, secrets/tokens, config objects

Operator does:
1. New endpoints → `echo JSON | ./scripts/dispatcher.sh $DB requeue`
2. Secrets/tokens → findings.md immediately (HIGH/MEDIUM) + `intel-secrets.json` for full values + intel.md Credentials table for preview/reference only
3. Interesting routes → requeue as new cases
4. Web3/NFT/unusual endpoints → requeue with HIGH priority note

## VULNERABILITY-ANALYST → exploit-developer / fuzzer

### During CONSUME & TEST:

vuln-analyst returns: prioritized findings (HIGH/MEDIUM/LOW), test commands, FUZZER_NEEDED blocks

Operator does:
1. HIGH/MEDIUM confidence → IMMEDIATELY dispatch exploit-developer with:
   - Vulnerability type, location (endpoint+param), evidence, recommended test, objective
2. LOW confidence → record in findings.md, do NOT dispatch yet
3. FUZZER_NEEDED → dispatch fuzzer, feed results back through vuln-analyst

### During EXPLOIT phase:

1. Dispatch exploit-developer with FULL findings.md for comprehensive review
2. Exploit ALL remaining findings (including LOW and INFO)
3. Identify chains (multiple INFO/LOW → combined HIGH impact)
4. Reassess severity based on actual exploitation

## FUZZER → vuln-analyst / findings

fuzzer outputs: discovered paths, valid parameters, anomalous responses

Operator does:
1. New paths/endpoints → requeue into cases.db
2. Anomalous responses → dispatch vuln-analyst for analysis
3. Confirmed findings (e.g., valid credentials) → findings.md directly

## EXPLOIT-DEVELOPER → findings + next steps

exploit outputs: CONFIRMED/PARTIAL/FAILED status, extracted data, PoC

Operator does:
1. CONFIRMED → findings.md with full evidence (HIGH severity)
2. CONFIRMED + credentials → auth.json, login, POST-AUTH RE-COLLECTION
3. CONFIRMED + new attack surface → requeue new endpoints
4. PARTIAL → record as MEDIUM, consider fuzzer for deeper testing
5. FAILED → log.md, move to next finding

## OSINT-ANALYST → operator → exploit-developer

osint-analyst writes intel.md ONLY (never findings.md).

Operator does after completion:
1. Read Intelligence Assessment section
2. HIGH-value CVE + PoC match → write finding + dispatch exploit-developer
3. Breached credentials → write finding + dispatch exploit-developer
4. Historical endpoints → requeue to cases.db
5. MEDIUM/LOW → record as INFO in findings.md

## REPORT-WRITER ← operator provides

Engagement directory path with: scope.json, log.md, findings.md, intel.md, cases.db

## Wildcard Mode Specifics

- DUAL FINDING WRITE: every finding → child's findings.md + parent's findings.md
- Parent prefix: `## [sub.domain.com / FINDING-XX-NNN] Title`
- Set ENGAGEMENT_DIR to specific child directory before each operation
