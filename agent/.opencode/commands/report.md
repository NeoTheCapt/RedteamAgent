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
./scripts/check_surface_coverage.sh "$ENG_DIR"
```

If any check fails, stop and report the duplicate IDs, count mismatch, in-scope raw curl usage, or unresolved high-risk surfaces instead of generating a misleading report.

## Step 3: Generate Report

The report-generation skill is already loaded in your context as instructions. Do NOT invoke it as a skill tool. Follow its report format and methodology.

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

## Step 4: Finalize Engagement State

After generating `report.md`, run:

```bash
./scripts/finalize_engagement.sh "$ENG_DIR"
```

This is the single supported finalize path. It updates:
- `scope.json` (`status=complete`, `current_phase=complete`, `end_time`, `phases_completed += report`)
- `log.md` (`Status: Completed`)
- `report.md` header date/status lines
- SQLite WAL/SHM sidecars via checkpoint + cleanup

## User Arguments

Additional report instructions or scope from the user follows:
