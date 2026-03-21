# Command: Reconnaissance Phase

You are the recon-specialist executing a full reconnaissance cycle. This is a manual override command -- the user wants recon run (or re-run) with specific focus.

## Step 1: Load Engagement State

Locate the most recent engagement directory under `engagements/`. Read:
- `scope.json` -- target, scope boundaries, current phase
- `log.md` -- what has already been done (avoid duplication)
- `findings.md` -- existing findings to build upon

If no engagement exists, inform the user to run `/engage` first.

## Step 2: Follow web-recon Methodology

The web-recon skill is already loaded in your context as instructions. Do NOT invoke it as a skill tool or try to read the file. Simply follow its procedures for:
- HTTP response header analysis (Server, X-Powered-By, security headers)
- Technology fingerprinting (whatweb, wappalyzer, or manual inspection)
- robots.txt and sitemap.xml retrieval
- SSL/TLS certificate inspection (if HTTPS)
- DNS enumeration if applicable

## Step 3: Execute Recon

For each recon action:
1. Present the command to the user for approval before execution.
2. Execute the approved command.
3. Parse the output -- extract structured data (endpoints, technologies, versions, headers).
4. Log the action and results to `log.md` using the standard log format.

## Step 4: Output Summary

After completing the recon cycle, produce a summary containing:
- **Endpoints discovered**: URLs, paths, API routes
- **Technologies identified**: frameworks, servers, languages, versions
- **Security headers**: present and missing
- **Interesting observations**: anything that suggests attack vectors

Record any confirmed findings in `findings.md`.

## User Arguments

Additional context or focus areas from the user follows:
