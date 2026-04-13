# Command: Generate Engagement Report

You are the report-writer generating a final structured report for the current engagement.

## Step 1: Locate Engagement Directory

Resolve the active engagement via `resolve_engagement_dir`. If the user specifies a particular engagement in their arguments, use that one instead.

```bash
source scripts/lib/engagement.sh
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
```

If no active engagement exists, inform the user that no engagement was found.

## Step 2: Read Engagement Data

Read the following files from the engagement directory:
- `scope.json` -- target, scope, mode, timeline
- `log.md` -- full chronological log of all actions
- `findings.md` -- all confirmed findings with evidence

Before reading findings, validate them:

```bash
./scripts/check_findings_integrity.sh "$ENG_DIR"
./scripts/check_target_curl_usage.sh "$ENG_DIR"
./scripts/check_katana_usage.sh "$ENG_DIR"
./scripts/check_collection_health.sh "$ENG_DIR"
./scripts/check_surface_coverage.sh "$ENG_DIR"
```

If any check fails, stop and report the duplicate IDs, count mismatch, raw runtime bypasses,
collection failures, or unresolved high-risk surfaces instead of generating a misleading report.

## Step 3: Generate Report

Do NOT call the `skill` tool for report-generation. The required report format and methodology
are already defined in this command and in your agent instructions. Follow them directly.

Create `report.md` in the engagement directory with the following structure:

```markdown
# Penetration Test Report

## Executive Summary
- Target, scope, and engagement timeframe
- High-level summary of results (total findings by severity)
- Overall risk assessment

## Scope and Methodology
- Target definition and boundaries
- Tools and techniques used
- Methodology phases executed

## Findings

### [FINDING-NNN] Title
- **Severity**: HIGH | MEDIUM | LOW | INFO
- **OWASP Category**: classification
- **Type**: vulnerability type
- **Location**: endpoint and parameter
- **Description**: detailed explanation of the vulnerability
- **Evidence**:
  - Command: exact command
  - Response: relevant response excerpt
- **Impact**: what an attacker can achieve
- **Remediation**: recommended fix

(Repeat for each finding, ordered by severity: HIGH first, then MEDIUM, LOW, INFO)

## Attack Narrative
Chronological walkthrough of the engagement: what was discovered, what was tested, and how findings were confirmed. This tells the story of the assessment.
If there is no credible multi-step chain, include the exact sentence:
`No multi-step attack paths identified.`

## Recommendations
Prioritized list of remediation actions, grouped by effort (quick wins vs. longer-term fixes).

## Appendix
- Tool versions used
- Full scan outputs (reference file paths)
- Timeline of actions
```

## Step 4: Report Handoff to Operator

After generating `report.md`, do **not** call `./scripts/finalize_engagement.sh` from `report-writer`.
Finalization is operator-owned so the same post-report path works for both standard targets and continuous-observation targets.

Instead:
- For standard targets, return a concise success handoff that names the report path and says the operator must run `./scripts/finalize_engagement.sh "$ENG_DIR"` next.
- For continuous-observation targets, return the exact handoff marker below after writing `report.md` and stop there:

```text
Continuous-observation handoff:
- report written: <report-path>
- operator must enter continuous observation hold
- operator must run ./scripts/finalize_engagement.sh "$ENG_DIR"
```

Never mutate `scope.json`, `log.md`, or `report.md` status lines directly from `report-writer` after report generation. The operator-owned finalize step is the single supported completion path.

## User Arguments

Additional report instructions or scope from the user follows:
