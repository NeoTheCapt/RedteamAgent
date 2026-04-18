---
name: report-generation
description: Engagement report structure and formatting guidelines
origin: RedteamOpencode
---

# Report Generation

## When to Activate

- Engagement complete and findings collected, user invokes `/report`
- User requests summary, deliverable, or final output

## Severity Definitions

| Severity | Criteria |
|----------|----------|
| **HIGH** | Direct CIA impact, exploitable with minimal effort. Data breach, RCE, auth bypass. CVSS 7.0-10.0. |
| **MEDIUM** | Requires conditions or chaining. Stored XSS, IDOR on non-critical data, limited SQLi. CVSS 4.0-6.9. |
| **LOW** | Limited impact or hard to exploit. Reflected XSS, verbose errors, missing headers. CVSS 0.1-3.9. |
| **INFO** | No direct security impact. Observations, best-practice deviations, tech disclosures. CVSS 0.0. |

## Writing Style

Factual, evidence-based. No speculation — state conditions if impact is theoretical.
Quantify where possible. No hyperbole or marketing language.

## Report Structure

### 1. Executive Summary

```markdown
## Executive Summary
**Target:** [target]  **Scope:** [scope]  **Date:** [start] – [end]  **Tester:** [id]

| Severity | Count |
|----------|-------|
| HIGH | N | MEDIUM | N | LOW | N | INFO | N | **Total** | **N** |

[1-2 paragraph narrative: posture, most impactful findings, top recommendation.]
```

### 2. Methodology

```markdown
## Methodology
**Approach:** [Black/Grey/White-box, Manual/Automated/Hybrid]
**Phases:** 1. Recon 2. Enumeration 3. Vuln Discovery 4. Exploitation 5. Post-Exploitation

| Tool | Purpose |
|------|---------|

**Limitations:** [time, scope, rate limiting, unavailable systems]
```

### 3. Findings (sorted HIGH → INFO, each self-contained)

```markdown
### FINDING-001: [Title] [HIGH]
**OWASP:** A03:2021  **Component:** [endpoint/param]  **CVSS:** [score]

#### Description
[Precise technical explanation]

#### Evidence
**Request:** ```[full HTTP request]```
**Response:** ```[relevant excerpt]```

#### Impact
[Specific: "attacker can retrieve all 12,000 user credentials"]

#### Remediation
1. [Primary fix]  2. [Defense-in-depth]  3. [Monitoring]
**References:** [CWE, CVE links]
```

### 4. Attack Path Narrative

```markdown
## Attack Path Narrative
### Scenario 1: [Title]
**Findings Used:** FINDING-001, FINDING-003  **Starting Point:** [attacker type]
1. **Initial Access** — [FINDING-X] → [foothold]
2. **Escalation** — [FINDING-Y] → [escalate]
3. **Objective** — [outcome]
**Combined Impact:** [what chain achieves]  **Priority Fix:** [which fix breaks chain]
```

If no chains: "No multi-step attack paths identified."

### 5. Appendix

Tool output in `<details>` blocks, generated scripts, scope verification table, timeline.

## Generation Procedure

1. Collect and deduplicate findings
2. Assign severity per definitions, sort HIGH → INFO
3. Populate all template fields (flag missing evidence, never fabricate)
4. Analyze chaining opportunities, write attack path narrative
5. Compile appendix from tool output and scripts
6. Write executive summary LAST
7. Verify: finding IDs match cross-references, severity counts match
