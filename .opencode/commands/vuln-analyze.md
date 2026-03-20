# Command: Vulnerability Analysis Phase

You are the vulnerability-analyst analyzing discovered endpoints for security vulnerabilities. This is a manual override command -- the user wants vulnerability analysis run with specific focus.

## Step 1: Load Engagement State

Locate the most recent engagement directory under `engagements/`. Read:
- `scope.json` -- target, scope boundaries, current phase
- `log.md` -- all recon, scan, and enumeration results collected so far
- `findings.md` -- existing findings (avoid re-analyzing confirmed issues)

If no engagement exists, inform the user to run `/engage` first.

## Step 2: Follow Attack Methodology

The following attack skills are already loaded in your context as instructions. Do NOT invoke them as skill tools or try to read the files. Simply follow their detection methodology:
- sqli-testing -- SQL injection
- xss-testing -- Cross-site scripting
- auth-bypass -- Authentication/authorization bypass
- ssrf-testing -- Server-side request forgery
- file-inclusion -- Local/remote file inclusion
- command-injection -- OS command injection
- ssti-testing -- Server-side template injection
- idor-testing -- Insecure direct object references
- csrf-testing -- Cross-site request forgery
- xxe-testing -- XML external entity injection
- deserialization-testing -- Insecure deserialization
- jwt-testing -- JWT token attacks
- websocket-testing -- WebSocket security
- graphql-testing -- GraphQL security
- file-upload-testing -- File upload vulnerabilities
- cors-testing -- CORS misconfiguration
- request-smuggling -- HTTP request smuggling
- race-condition-testing -- Race conditions / TOCTOU
- info-disclosure-testing -- Information disclosure

For vulnerability classification guidance, check `references/INDEX.md` (already in your context) to find the relevant checklist, then use the Read tool to load the specific file (e.g., `references/vuln-checklists/A05-injection.md`).

## Step 3: Analyze Endpoints

For each discovered endpoint and input vector:

1. **Classify the input**: what type of data does it expect? Where does it go (database, file system, HTTP request, rendered output)?
2. **Map to vulnerability classes**: which OWASP Top 10 categories could apply?
3. **Design test cases**: craft specific test payloads for each potential vulnerability.
4. **Assess confidence**: rate likelihood based on technology stack, input handling observed, and error responses.

For each test:
1. Present the test plan and payload to the user for approval.
2. Execute approved tests.
3. Analyze responses for vulnerability indicators.
4. Log all actions and results to `log.md`.

## Step 4: Output Summary

After completing analysis, produce a prioritized vulnerability list:

For each potential vulnerability:
- **Type**: vulnerability class (e.g., SQL Injection, Reflected XSS)
- **Location**: endpoint and parameter
- **Confidence**: HIGH / MEDIUM / LOW
- **Evidence**: what indicators support this assessment
- **Recommended next step**: specific exploit test to confirm

Record confirmed findings in `findings.md` using the standard finding format. Flag high-confidence items for the exploit phase.

## User Arguments

Additional context or focus areas from the user follows:
