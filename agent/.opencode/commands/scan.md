# Command: Active Scanning Phase

You are the recon-specialist executing active port and service scanning. This is a manual override command -- the user wants scanning run with specific focus.

## Step 1: Load Engagement State

Resolve the active engagement via `resolve_engagement_dir`. Read:
- `scope.json` -- target, scope boundaries, current phase
- `log.md` -- what has already been done
- `findings.md` -- existing findings

```bash
source scripts/lib/engagement.sh
ENG_DIR=$(resolve_engagement_dir "$(pwd)")
```

If no active engagement exists, inform the user to run `/engage` first.

## Step 2: Follow port-scanning Methodology

The port-scanning skill is already loaded in your context as instructions. Do NOT invoke it as a skill tool or try to read the file. Simply follow its procedures for:
- TCP port scanning (common ports first, then full range if needed)
- Service version detection
- OS fingerprinting
- Script scanning for known vulnerabilities (nmap NSE scripts)

## Step 3: Execute Scanning

For each scan action:
1. **INTERACTIVE / manual-confirm**: present the scan command to the user for approval before execution.
2. **AUTO-CONFIRM / AUTONOMOUS**: announce the scan command, then execute immediately.
3. Parse output -- extract open ports, service names, versions, OS details.
4. Log the action and results to `log.md` using the standard log format.

Save raw scan output to the engagement directory for reference (e.g., `nmap-output.txt`).

## Step 4: Output Summary

After completing scanning, produce a summary containing:
- **Open ports**: port number, protocol, service, version
- **Service versions**: exact version strings for vulnerability lookup
- **OS detection**: if determined
- **Notable services**: anything unusual or potentially vulnerable

Record any confirmed findings (e.g., outdated service versions) in `findings.md`.

## User Arguments

Additional context or focus areas from the user follows:
