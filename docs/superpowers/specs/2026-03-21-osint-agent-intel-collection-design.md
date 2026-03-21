# OSINT Agent & Intelligence Collection Design

**Date**: 2026-03-21
**Status**: Draft
**Scope**: New osint-analyst agent, intel.md file, recon/source-analyzer output changes, operator workflow changes

## Problem

Recon-specialist and source-analyzer discover valuable intelligence (tech stack versions, people, companies, emails, domains, credentials) that is currently scattered across findings.md (as INFO severity) and agent output. This intelligence is never systematically analyzed against external data sources (CVE databases, breach databases, DNS history, social profiles) to enrich the attack context.

## Solution

1. Introduce `intel.md` as a dedicated intelligence collection file in each engagement
2. Modify recon-specialist and source-analyzer to output an `#### Intelligence` section
3. Create a new osint-analyst agent that consumes intel.md and enriches it via online OSINT tools
4. osint-analyst runs parallel with exploit-developer in the EXPLOIT phase
5. Operator acts as the sole translation layer between intel.md and findings.md

## Design

### 1. intel.md File Format

Created at engagement initialization alongside scope.json, log.md, findings.md.

```markdown
# Intelligence Collection

## Technology Stack
| Component | Version | Source | Confidence |
|-----------|---------|--------|------------|

## People & Organizations
| Name | Role/Context | Source | Notes |
|------|-------------|--------|-------|

## Email Addresses
| Email | Source | Notes |
|-------|--------|-------|

## Domains & Infrastructure
| Item | Type | Source | Notes |
|------|------|--------|-------|

## Credentials & Secrets
| Type | Value (truncated) | Source | Notes |
|------|-------------------|--------|-------|

## Raw OSINT (populated by osint-analyst)

### CVE & Known Vulnerabilities
| CVE | Affected | CVSS | PoC Available | Source |
|-----|----------|------|---------------|--------|

### Breach & Leak Data
| Email/Domain | Breach | Date | Data Types | Source |
|-------------|--------|------|------------|--------|

### DNS & Certificate History
| Record | Value | First Seen | Last Seen | Source |
|--------|-------|------------|-----------|--------|

### Social & OSINT Profiles
| Person/Org | Platform | URL/Handle | Notes |
|-----------|----------|------------|-------|
```

- Top half (Technology Stack → Credentials & Secrets): written by recon-specialist and source-analyzer
- Bottom half (Raw OSINT): written by osint-analyst
- Operator appends to the corresponding section after receiving agent output, deduplicating entries

### 2. recon-specialist Output Format Change

Add to the end of OUTPUT FORMAT, after `#### Recommended Follow-Up`:

```markdown
#### Intelligence
Extracted intel for intel.md. ONLY include items actually discovered — omit empty tables.

Technology Stack:
| Component | Version | Source | Confidence |

People & Organizations:
| Name | Role/Context | Source | Notes |

Email Addresses:
| Email | Source | Notes |

Domains & Infrastructure:
| Item | Type | Source | Notes |
```

recon-specialist does not output Credentials (its discoveries are primarily version/header level).

### 3. source-analyzer Output Format Change

Add to the end of OUTPUT FORMAT, after `#### Recommended Follow-Up`:

```markdown
#### Intelligence
Extracted intel for intel.md. ONLY include items actually discovered — omit empty tables.

Technology Stack:
| Component | Version | Source | Confidence |

People & Organizations:
| Name | Role/Context | Source | Notes |

Email Addresses:
| Email | Source | Notes |

Credentials & Secrets:
| Type | Value (truncated) | Source | Notes |

Domains & Infrastructure:
| Item | Type | Source | Notes |
```

source-analyzer includes Credentials because it extracts hardcoded keys/tokens from JS/CSS.

### 4. osint-analyst Agent Definition

Platform-agnostic prompt shared across Claude Code, Codex, and OpenCode:

```
You are the OSINT analyst subagent (agent name: osint-analyst). You perform open-source
intelligence gathering against authorized CTF/lab targets using online data sources and
OSINT tools. You consume intel.md as input and enrich it with external intelligence.

PREFIX all output with [osint-analyst].

=== INPUT CONTRACT ===

Operator provides: engagement path (with intel.md), scope, target domain/org, specific
intelligence objectives.

=== SKILLS ===

Read skill files from skills/*/SKILL.md when needed: osint-recon

=== INTELLIGENCE DOMAINS ===

1. CVE & VULNERABILITY INTELLIGENCE
   - Query NVD/CVE databases for known vulns matching discovered tech+version
   - Search Exploit-DB for public PoCs
   - Check GitHub for PoC repos and advisories
   - Tools: searchsploit, curl (NVD API, GitHub API)

2. BREACH & CREDENTIAL INTELLIGENCE
   - Email/domain breach lookups
   - Paste site monitoring for leaked credentials
   - Tools: h8mail, curl (HIBP API, dehashed API)

3. DNS & INFRASTRUCTURE HISTORY
   - WHOIS current and historical records
   - DNS history and zone transfers
   - Certificate transparency logs
   - ASN and IP range mapping
   - Wayback Machine for historical endpoints
   - Tools: whois, dig, curl (crt.sh, SecurityTrails API, web.archive.org API), amass

4. SOCIAL & ORGANIZATIONAL INTELLIGENCE
   - People/org discovered in intel.md → social media profiles
   - GitHub repos, code contributions, leaked internal docs
   - Organizational structure and employee enumeration
   - Tools: theHarvester, spiderfoot, curl (GitHub API, Hunter.io API)

=== OUTPUT FORMAT ===

### OSINT Results: <objective>
**Target**: <domain/org>  **Intel Source**: intel.md  **Tools Used**: <list>

#### CVE & Known Vulnerabilities
| CVE | Affected Component | CVSS | PoC Available | Source |
|-----|-------------------|------|---------------|--------|

#### Breach & Leak Data
| Email/Domain | Breach | Date | Data Types | Source |
|-------------|--------|------|------------|--------|

#### DNS & Certificate History
| Record | Value | First Seen | Last Seen | Source |
|--------|-------|------------|-----------|--------|

#### Social & OSINT Profiles
| Person/Org | Platform | URL/Handle | Notes |
|-----------|----------|------------|-------|

#### Intelligence Assessment
- High-value intel with reasoning (operator decides next action)
- e.g., "Apache 2.4.49 has CVE-2021-41773 with public PoC — recommend exploit-developer verify"
- e.g., "admin@target.com appeared in 2023 LinkedIn breach — credential reuse possible"

#### Recommended Follow-Up (return to operator — do NOT execute)

=== EXECUTION RULES ===

1. Execute ONLY the assigned intelligence objective.
2. Start by reading intel.md — build queries from discovered tech, people, domains.
3. Do NOT perform active scanning, vulnerability testing, or exploitation. Passive intelligence collection ONLY.
4. Respect API rate limits. Cache responses to engagement scans/ directory.
5. Prioritize: CVE matches with PoC > leaked credentials > historical endpoints > social profiles.
6. Cross-reference multiple sources before marking confidence HIGH.
7. Parse and structure all output — never return raw tool dumps.
8. Save raw tool output to scans/osint_*.txt for traceability.
```

### 5. osint-recon Skill

New skill at `skills/osint-recon/SKILL.md`:

```markdown
---
name: osint-recon
description: Open-source intelligence gathering — CVE lookup, breach search, DNS history, social profiling
origin: RedteamOpencode
---

# OSINT Reconnaissance

## When to Activate

- After TEST phase, intel.md has accumulated tech stack, people, domains, credentials
- Parallel with exploit phase to enrich attack context

## Tools

searchsploit, h8mail, theHarvester, spiderfoot, amass, whois, dig,
waybackurls, curl, jq

## Methodology

### 1. CVE & Exploit Lookup

From intel.md Technology Stack — for each component+version:

    # Exploit-DB local search
    searchsploit "<component> <version>"
    searchsploit -j "<component> <version>" | jq '.RESULTS_EXPLOIT[]'

    # NVD API (rate limit: 5 req/30s without API key)
    curl -s "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=<component>+<version>&resultsPerPage=10" \
      | jq '.vulnerabilities[].cve | {id, descriptions: .descriptions[0].value, metrics: .metrics}'

    # GitHub Advisory Database
    curl -s "https://api.github.com/advisories?affects=<component>&per_page=10" \
      | jq '.[].ghsa_id, .[].summary'

    # GitHub PoC search
    curl -s "https://api.github.com/search/repositories?q=CVE+<component>+poc&sort=updated&per_page=5" \
      | jq '.items[] | {name, html_url, description}'

### 2. Breach & Credential Intelligence

From intel.md Email Addresses and Domains:

    # theHarvester — email and subdomain enumeration
    theHarvester -d <domain> -b all -f scans/osint_harvester.json

    # h8mail — breach lookup for discovered emails
    h8mail -t <email1>,<email2> -o scans/osint_h8mail.csv

    # HIBP API (requires API key in env)
    curl -s -H "hibp-api-key: $HIBP_API_KEY" \
      "https://haveibeenpwned.com/api/v3/breachedaccount/<email>?truncateResponse=false" | jq '.'

    # Paste search
    curl -s -H "hibp-api-key: $HIBP_API_KEY" \
      "https://haveibeenpwned.com/api/v3/pasteaccount/<email>" | jq '.'

### 3. DNS & Infrastructure History

From intel.md Domains & Infrastructure:

    # WHOIS
    whois <domain> | tee scans/osint_whois.txt

    # Certificate transparency
    curl -s "https://crt.sh/?q=%25.<domain>&output=json" \
      | jq '.[0:20] | .[] | {name_value, issuer_name, not_before, not_after}'

    # DNS records
    for type in A AAAA MX NS TXT SOA CNAME; do
      dig +short $type <domain>
    done | tee scans/osint_dns.txt

    # Amass passive enum
    amass enum -passive -d <domain> -o scans/osint_amass.txt

    # Wayback Machine — historical URLs
    curl -s "https://web.archive.org/cdx/search/cdx?url=<domain>/*&output=json&fl=original,timestamp,statuscode&collapse=urlkey&limit=200" \
      | jq '.[1:][] | {url: .[0], date: .[1], status: .[2]}'

    # SecurityTrails API (requires API key in env)
    curl -s -H "APIKEY: $SECURITYTRAILS_API_KEY" \
      "https://api.securitytrails.com/v1/domain/<domain>/subdomains" | jq '.subdomains[]'

    # Historical DNS
    curl -s -H "APIKEY: $SECURITYTRAILS_API_KEY" \
      "https://api.securitytrails.com/v1/history/<domain>/dns/a" | jq '.records[]'

### 4. Social & Organizational Intelligence

From intel.md People & Organizations:

    # theHarvester — people and email enumeration
    theHarvester -d <domain> -b linkedin,google -f scans/osint_social.json

    # SpiderFoot CLI scan
    spiderfoot -s <domain> -m sfp_dnsresolve,sfp_whois,sfp_social,sfp_email \
      -o scans/osint_spiderfoot.json

    # GitHub user/org search
    curl -s "https://api.github.com/search/users?q=<person>+<org>" \
      | jq '.items[] | {login, html_url, type}'

    # GitHub org repos (potential source code leaks)
    curl -s "https://api.github.com/orgs/<org>/repos?per_page=30&sort=updated" \
      | jq '.[] | {name, html_url, description, visibility}'

    # Hunter.io — email pattern discovery (requires API key)
    curl -s "https://api.hunter.io/v2/domain-search?domain=<domain>&api_key=$HUNTER_API_KEY" \
      | jq '.data.emails[] | {value, type, confidence}'

## Priority Order

1. CVE + version match with public PoC (immediate exploit value)
2. Leaked/breached credentials for target emails (direct access)
3. Historical endpoints not in current attack surface (hidden functionality)
4. Organizational intel enriching social engineering context
5. DNS/cert history revealing infrastructure changes

## Output Integration

ALL output goes to intel.md ONLY. osint-analyst does NOT write to findings.md.
- CVE matches → intel.md CVE table + Intelligence Assessment
- Breached credentials → intel.md Breach table + Intelligence Assessment
- Historical URLs → intel.md DNS table (operator decides whether to requeue)
- Social/org intel → intel.md Social table
```

### 5a. Tool Execution Model & API Key Handling

**Host vs Docker:**
- `curl`, `jq`, `dig`, `whois` — run on host (consistent with existing rule)
- `searchsploit`, `h8mail`, `theHarvester`, `spiderfoot`, `amass`, `nuclei`, `waybackurls` — run via `run_tool` (Docker)

**API Key Graceful Degradation:**

osint-analyst checks each API key before use. If missing, skip that source and note it:

| API Key Env Var | Service | Required? |
|-----------------|---------|-----------|
| (none) | NVD, crt.sh, GitHub (unauthenticated), Wayback | No — free/public |
| `HIBP_API_KEY` | Have I Been Pwned | Optional — skip breach lookup if absent |
| `SECURITYTRAILS_API_KEY` | SecurityTrails | Optional — skip DNS history if absent |
| `HUNTER_API_KEY` | Hunter.io | Optional — skip email pattern discovery if absent |

Agent rule: "If an API key env var is empty, log `[osint-analyst] Skipping <service> — API key not configured` and move to next source. Never error on missing keys."

### 5b. intel.md Deduplication Keys

When operator appends Intelligence output to intel.md, deduplicate by these keys:

| Table | Dedup Key |
|-------|-----------|
| Technology Stack | Component |
| People & Organizations | Name |
| Email Addresses | Email |
| Domains & Infrastructure | Item + Type |
| Credentials & Secrets | Type + Source |
| CVE & Known Vulnerabilities | CVE |
| Breach & Leak Data | Email/Domain + Breach |
| DNS & Certificate History | Record + Value |
| Social & OSINT Profiles | Person/Org + Platform |

If a duplicate is found with new information (e.g., higher Confidence, additional Notes), update the existing row rather than appending.

### 6. Operator Workflow Changes

#### Phase Transition Update

Phases remain numbered 1-5. EXPLOIT phase (4) gains internal parallelism:

```
Phase 1: RECON     — dispatch recon-specialist + source-analyzer (parallel)
                     Both output Intelligence section → operator appends to intel.md
Phase 2: COLLECT   — import endpoints → cases.db, start Katana
Phase 3: TEST      — dispatcher loop, vuln-analyst/fuzzer
Phase 4: EXPLOIT   — dispatch osint-analyst + exploit-developer (parallel)
                     osint-analyst completes → operator reads intel.md:
                       HIGH value → write findings.md + dispatch exploit-developer (2nd round)
                       historical endpoints → requeue cases.db
Phase 5: REPORT    — dispatch report-writer (intel.md as report appendix)
```

#### New Mandatory Dispatch Rules

```
EXPLOIT PHASE:
  - ALWAYS dispatch osint-analyst IN PARALLEL with exploit-developer
  - osint-analyst input: engagement path + intel.md
  - exploit-developer input: findings.md (existing rule, unchanged)
  - AFTER osint-analyst completes:
    read intel.md Intelligence Assessment
    HIGH value items → write findings.md + dispatch exploit-developer (second round)
    historical endpoints → requeue to cases.db
```

#### Engagement Directory Update

```
engagements/<date>-<HHMMSS>-<hostname>/
├── scope.json
├── log.md
├── findings.md
├── intel.md          ← NEW
├── cases.db
├── auth.json
├── downloads/
├── scans/
├── tools/
└── pids/
```

#### New Agent in Roster

```
osint-analyst — OSINT intelligence gathering, CVE/breach/DNS/social research.
               Dispatched in EXPLOIT phase parallel with exploit-developer.
```

#### New Handoff Protocol

```
OSINT-ANALYST → operator → exploit-developer:

WHEN osint-analyst completes:
  1. Read intel.md Intelligence Assessment section
  2. For each HIGH-value assessment:

     a. CVE + confirmed version match + public PoC:
        → Write to findings.md:
          ## [FINDING-NNN] Known CVE: <CVE-ID>
          - Severity: HIGH
          - Type: Known Vulnerability (OSINT)
          - Evidence: intel.md CVE table entry + PoC reference
          - Impact: <from CVE description>
        → Dispatch exploit-developer: "Verify and exploit <CVE-ID>
          against <component> <version>. PoC reference: <url>"

     b. Breached credentials matching target:
        → Write to findings.md:
          ## [FINDING-NNN] Potential Credential Reuse
          - Severity: HIGH
          - Type: Credential Exposure (OSINT)
          - Evidence: intel.md Breach table entry
        → Dispatch exploit-developer: "Test credential reuse
          for <email> against login endpoints. Breach source: <breach>"

     c. Historical endpoints not in current scope:
        → Requeue to cases.db via dispatcher.sh requeue
        → Normal consumption loop picks them up

  3. For MEDIUM/LOW assessments:
     → Record in findings.md as INFO severity
     → Available for chain analysis in EXPLOIT phase

OSINT-ANALYST → operator → vulnerability-analyst:
  Historical endpoints requeued to cases.db flow through
  normal consumption loop. No special handling needed.
```

#### Report Integration

report-writer input gains intel.md. Report adds "Intelligence Summary" section listing key intel findings and their contribution to exploitation.

### 7. Configuration Changes

#### opencode.json

Add to agents (matching existing format):

```json
"osint-analyst": {
  "description": "OSINT intelligence gathering — CVE/breach/DNS/social research. Dispatched in EXPLOIT phase parallel with exploit-developer.",
  "mode": "subagent",
  "prompt": "{file:prompts/agents/osint-analyst.txt}",
  "read": true,
  "write": false,
  "edit": false,
  "bash": true,
  "glob": true,
  "grep": true
}
```

Add `/osint` command to commands (matching existing pattern):

```json
"osint": {
  "description": "Run OSINT intelligence gathering on current engagement",
  "agent": "osint-analyst"
}
```

Add to instructions array:

```json
"skills/osint-recon/SKILL.md"
```

## File Change Summary

### New Files (4)

| File | Purpose |
|------|---------|
| `agent/skills/osint-recon/SKILL.md` | OSINT methodology skill |
| `agent/.claude/agents/osint-analyst.md` | Claude Code agent definition |
| `agent/.codex/agents/osint-analyst.toml` | Codex agent definition |
| `agent/.opencode/prompts/agents/osint-analyst.txt` | OpenCode agent definition |

### Modified Files (17)

| File | Change |
|------|--------|
| `agent/.claude/agents/recon-specialist.md` | Add `#### Intelligence` to OUTPUT FORMAT |
| `agent/.codex/agents/recon-specialist.toml` | Same |
| `agent/.opencode/prompts/agents/recon-specialist.txt` | Same |
| `agent/.claude/agents/source-analyzer.md` | Add `#### Intelligence` (with Credentials) to OUTPUT FORMAT |
| `agent/.codex/agents/source-analyzer.toml` | Same |
| `agent/.opencode/prompts/agents/source-analyzer.txt` | Same |
| `agent/.claude/agents/report-writer.md` | Add intel.md to DATA SOURCES, add Intelligence Summary to REPORT STRUCTURE |
| `agent/.codex/agents/report-writer.toml` | Same |
| `agent/.opencode/prompts/agents/report-writer.txt` | Same |
| `agent/CLAUDE.md` | Agent roster (osint-analyst), EXPLOIT parallel rule, intel.md write rule, OSINT handoff, engagement init (intel.md), report input, skill count 30→31, Phase 4 description update |
| `agent/AGENTS.md` | Same |
| `agent/.opencode/prompts/agents/operator.txt` | Same |
| `agent/.opencode/opencode.json` | Add osint-analyst agent, add /osint command, add osint-recon skill path |
| `agent/.opencode/commands/engage.md` | Add intel.md template creation in Step 2 engagement init |
| `agent/.claude/commands/engage.md` | Same (if exists, otherwise engagement init is in operator prompt) |
| `agent/.codex/agents/operator.toml` | Engagement init rule includes intel.md creation |
| `agent/.opencode/commands/osint.md` | New /osint command template |

### Unchanged Files

- dispatcher.sh / schema.sql — historical endpoints use existing requeue mechanism
- Hook scripts / plugins — platform-specific, not touched
- Other agents (vuln-analyst, exploit-developer, fuzzer) — prompts unchanged, operator passes intel via dispatch instructions
