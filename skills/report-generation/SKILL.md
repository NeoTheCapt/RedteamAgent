---
name: report-generation
description: Engagement report structure and formatting guidelines
origin: RedteamOpencode
---

# Report Generation

## When to Activate

- Engagement testing is complete and all findings have been collected
- User invokes `/report`
- User requests a summary, deliverable, or final output of the engagement
- Transitioning from active testing to documentation phase

## Severity Definitions

| Severity | Criteria |
|----------|----------|
| **HIGH** | Direct impact on confidentiality, integrity, or availability. Exploitable without authentication or with minimal effort. Data breach, RCE, privilege escalation, authentication bypass on critical functions. CVSS 7.0–10.0 equivalent. |
| **MEDIUM** | Requires specific conditions or chained exploitation. Stored XSS, IDOR on non-critical data, SQL injection with limited output, session fixation. CVSS 4.0–6.9 equivalent. |
| **LOW** | Limited impact or difficult to exploit. Reflected XSS requiring social engineering, verbose error messages leaking internal paths, missing non-critical security headers. CVSS 0.1–3.9 equivalent. |
| **INFO** | No direct security impact. Observations, best-practice deviations, technology disclosures, or items noted for awareness. CVSS 0.0. |

## Writing Style

- Factual, technical, evidence-based. Every claim must reference concrete evidence.
- No speculation. If impact is theoretical, state the conditions required for exploitation.
- Use passive voice sparingly; prefer direct statements ("The server returned...", "The parameter accepts...").
- Quantify where possible: response times, payload lengths, number of records exposed.
- Avoid marketing language, hyperbole, or subjective risk characterizations.

## Report Structure

### 1. Executive Summary

High-level overview for technical and non-technical stakeholders.

```markdown
## Executive Summary

**Target:** [target name / URL / IP range]
**Scope:** [in-scope systems, endpoints, and restrictions]
**Date:** [start date] – [end date]
**Duration:** [total testing hours/days]
**Tester:** [operator identifier]

### Summary of Findings

| Severity | Count |
|----------|-------|
| HIGH     | N     |
| MEDIUM   | N     |
| LOW      | N     |
| INFO     | N     |
| **Total**| **N** |

[1-2 paragraph narrative: overall security posture, most impactful findings,
whether critical business functions are affected, and top-level recommendation.]
```

### 2. Methodology

Describe the approach, phases, and tooling used during the engagement.

```markdown
## Methodology

### Approach

[Black-box / Grey-box / White-box. Manual / Automated / Hybrid.]

### Phases Executed

1. **Reconnaissance** — [brief description of what was done]
2. **Enumeration** — [brief description]
3. **Vulnerability Discovery** — [brief description]
4. **Exploitation** — [brief description]
5. **Post-Exploitation** — [brief description, if applicable]

### Tools Used

| Tool | Purpose |
|------|---------|
| [tool name] | [what it was used for] |
| [tool name] | [what it was used for] |

### Limitations

[Any constraints that affected testing: time limits, scope restrictions,
rate limiting encountered, systems that were unavailable.]
```

### 3. Findings

Each finding is a self-contained section. Sort by severity: HIGH first, then MEDIUM, LOW, INFO.

```markdown
## Findings

### FINDING-001: [Title] [HIGH]

**OWASP Category:** [e.g., A03:2021 — Injection]
**Affected Component:** [URL, endpoint, parameter, or system]
**CVSS Score:** [if calculated]

#### Description

[What was found. Precise technical explanation of the vulnerability.
Reference the specific parameter, endpoint, or configuration.]

#### Evidence

**Request:**

```http
POST /api/login HTTP/1.1
Host: target.example.com
Content-Type: application/json

{"username": "admin' OR 1=1--", "password": "anything"}
```

**Response:**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "authenticated", "user": "admin", "token": "eyJ..."}
```

[Additional screenshots, tool output, or data samples as needed.]

#### Impact

[What an attacker could achieve by exploiting this vulnerability.
Be specific: "An unauthenticated attacker could retrieve all user records
from the database, including plaintext passwords for 12,000 accounts."]

#### Remediation

[Specific, actionable fix recommendation. Reference the technology in use.]

1. [Primary fix — e.g., "Use parameterized queries for all SQL operations in the /api/login endpoint."]
2. [Defense-in-depth — e.g., "Implement input validation rejecting SQL metacharacters."]
3. [Monitoring — e.g., "Add WAF rules to detect SQL injection patterns."]

**References:**
- [relevant CWE, CVE, or documentation link]
```

### 4. Attack Path Narrative

Describe how individual findings chain together to form realistic attack scenarios.

```markdown
## Attack Path Narrative

### Scenario 1: [Descriptive Title]

**Findings Used:** FINDING-001, FINDING-003, FINDING-005
**Starting Point:** [unauthenticated external attacker / authenticated low-privilege user / etc.]

**Step-by-step path:**

1. **Initial Access** — Attacker exploits [FINDING-X] to [gain foothold].
   - Evidence: [reference to finding]
2. **Escalation** — Using access from step 1, attacker leverages [FINDING-Y] to [escalate].
   - Evidence: [reference to finding]
3. **Objective** — Attacker achieves [data exfiltration / admin access / lateral movement].
   - Evidence: [reference to finding]

**Combined Impact:** [What the full chain achieves that individual findings alone do not.]

**Combined Remediation Priority:** [Which fix in the chain breaks it most effectively.]
```

If findings do not chain together, state that explicitly: "No multi-step attack paths were identified. Each finding is independently exploitable and independently remediable."

### 5. Appendix

Raw data, full tool output, and any generated scripts.

```markdown
## Appendix

### A. Full Tool Output Logs

#### A.1 [Tool Name] — [Target/Phase]

<details>
<summary>Click to expand</summary>

```
[full unedited tool output]
```

</details>

#### A.2 [Tool Name] — [Target/Phase]

<details>
<summary>Click to expand</summary>

```
[full unedited tool output]
```

</details>

### B. Generated Scripts

#### B.1 [Script Name] — [Purpose]

```bash
#!/usr/bin/env bash
# [description of what this script does]
[full script content]
```

### C. Scope Verification

| Target | In Scope | Tested | Notes |
|--------|----------|--------|-------|
| [host/URL] | Yes | Yes | [any notes] |

### D. Timeline

| Date | Activity |
|------|----------|
| [date] | [activity performed] |
```

## Generation Procedure

1. Collect all findings from the engagement session (scan results, manual tests, exploitation output).
2. Deduplicate findings — merge entries that describe the same underlying issue.
3. Assign severity to each finding using the definitions above.
4. Sort findings HIGH → MEDIUM → LOW → INFO.
5. For each finding, populate all template fields. If evidence is missing, flag it and do not fabricate data.
6. Analyze findings for chaining opportunities and write the attack path narrative.
7. Compile appendix from raw tool output and any custom scripts generated during testing.
8. Write the executive summary last, after all findings and narratives are complete.
9. Review the full report for consistency: finding IDs match cross-references, severity counts in the executive summary match the findings section.

## What to Record

- **Every finding** with complete evidence (request, response, tool output)
- **Severity justification** tied to the definitions table above
- **OWASP mapping** for each finding
- **Remediation** that is specific to the target's technology stack
- **Attack chains** where multiple findings combine for greater impact
- **Scope coverage** confirming which targets were tested
- **Limitations** that may have prevented discovery of additional issues
