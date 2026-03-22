---
name: info-disclosure-testing
description: Information disclosure detection — error messages, files, headers, debug endpoints
origin: RedteamOpencode
---

# Information Disclosure Testing

## When to Activate

- Reconnaissance phase of any engagement
- Verbose error messages observed
- Debug features suspected in production
- Sensitive data exposure assessment

## Tools

- `run_tool curl` (header inspection, file probing)
- Burp Suite (passive scanning, response analysis)
- `run_tool gobuster` / `run_tool ffuf` (file and directory brute-force)
- GitTools (extract .git repositories)
- trufflehog / gitleaks (secret scanning)

## Methodology

### 1. HTTP Header Analysis

- [ ] Check `Server` header — reveals web server and version
- [ ] Check `X-Powered-By` — reveals framework (PHP, ASP.NET, Express)
- [ ] Check `X-Debug-Token` / `X-Debug-Token-Link` — Symfony profiler
- [ ] Check `X-AspNet-Version`, `X-AspNetMvc-Version`
- [ ] Check `X-Request-Id` — internal request tracking
- [ ] Look for custom headers leaking internal hostnames or IPs
- [ ] Send OPTIONS request — check allowed methods

### 2. Error Message Analysis

- [ ] Trigger errors: invalid input, SQL syntax, type mismatch
- [ ] Look for stack traces with file paths, line numbers
- [ ] SQL error messages revealing query structure and DB type
- [ ] Framework debug pages: Django debug, Laravel Ignition, Spring Whitelabel
- [ ] PHP errors: `Warning:`, `Fatal error:`, `Notice:`
- [ ] Detailed 404/500 pages vs generic error pages

### 3. Sensitive File Discovery

- [ ] `/.git/` → `/.git/HEAD`, `/.git/config` (source code recovery)
- [ ] `/.env` — environment variables, database credentials, API keys
- [ ] `/.DS_Store` — macOS directory listing
- [ ] `/robots.txt` — disallowed paths reveal hidden functionality
- [ ] `/sitemap.xml` — full URL inventory
- [ ] `/.svn/entries` — Subversion metadata
- [ ] `/WEB-INF/web.xml` — Java web app configuration
- [ ] `/server-status`, `/server-info` — Apache status pages

### 4. Backup and Temporary Files

- [ ] `index.php.bak`, `config.php.old`, `database.yml~`
- [ ] `backup.zip`, `backup.tar.gz`, `db_dump.sql`
- [ ] `.swp` files (Vim swap): `.index.php.swp`
- [ ] Editor backups: `#file#`, `file~`, `file.save`
- [ ] Copy artifacts: `config.php.orig`, `web.config.bak`
- [ ] Compressed source: `www.zip`, `html.tar.gz`, `source.tgz`

### 5. Debug and Admin Endpoints

- [ ] `/actuator` — Spring Boot actuator (env, health, beans, mappings)
- [ ] `/actuator/env` — environment variables and secrets
- [ ] `/debug`, `/debug/vars`, `/debug/pprof` — Go debug
- [ ] `/_profiler` — Symfony profiler
- [ ] `/elmah.axd` — .NET error log
- [ ] `/trace`, `/metrics`, `/health`, `/info`
- [ ] `/phpinfo.php`, `/info.php` — PHP configuration dump
- [ ] `/console` — Spring Boot H2 console, Rails console

### 6. API Response Analysis

- [ ] Check for excessive data in API responses (PII, internal IDs, timestamps)
- [ ] Compare authenticated vs unauthenticated responses
- [ ] Check if error responses contain more data than success
- [ ] Look for internal IP addresses, hostnames in responses
- [ ] Check pagination: can you request all records?
- [ ] GraphQL introspection for full schema

### 7. Client-Side Disclosure

- [ ] HTML comments: `<!-- TODO: remove before prod -->`, credentials, internal URLs
- [ ] JavaScript source maps: `.js.map` files expose original source
- [ ] Inline secrets in JavaScript: API keys, tokens, credentials
- [ ] Hidden form fields with sensitive defaults
- [ ] Local storage / session storage containing tokens or PII
- [ ] Service worker caching sensitive data

### 8. Version and Technology Detection

- [ ] Default error pages reveal software version
- [ ] Cookie names: `JSESSIONID` (Java), `PHPSESSID` (PHP), `ASP.NET_SessionId`
- [ ] URL patterns: `.jsp`, `.php`, `.aspx`
- [ ] Response behavior fingerprinting
- [ ] `/favicon.ico` hash → identify framework/CMS

## What to Record

- Each disclosure finding with exact location (URL, header, response body)
- Data exposed: credentials, source code, internal architecture, PII
- Screenshots/evidence of error messages and debug pages
- Severity: Low (version info) to Critical (credentials, source code)
- Chain potential: how disclosure enables further attacks
- Remediation: custom error pages, remove debug endpoints, restrict files, strip headers
