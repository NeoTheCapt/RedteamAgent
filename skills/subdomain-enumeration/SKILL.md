---
name: subdomain-enumeration
description: Subdomain discovery via subfinder, DNS brute-force, and passive sources
origin: RedteamOpencode
---

# Subdomain Enumeration

## When to Activate

- Beginning of engagement when scope includes wildcard domains (*.target.com)
- Need to discover additional attack surface beyond the primary domain
- Recon phase — run in parallel with other recon tasks
- After finding references to subdomains in JS/HTML source code

## Tools

- `subfinder` — passive subdomain enumeration (multiple sources, API keys optional)
- `run_tool ffuf` — DNS brute-force via vhost fuzzing
- `curl` / `run_tool nmap` — verify discovered subdomains are live

## Methodology

### 1. Passive Enumeration with subfinder

subfinder queries 40+ passive sources (crt.sh, VirusTotal, Shodan, SecurityTrails, etc.)
without sending traffic to the target.

```bash
# Basic enumeration
run_tool subfinder -d target.com -silent

# With all sources (uses API keys from /engagement/.env if mounted)
run_tool subfinder -d target.com -all -silent -o /engagement/scans/subdomains.txt

# Multiple domains
run_tool subfinder -dL /engagement/scans/domains.txt -silent -o /engagement/scans/subdomains.txt

# JSON output for detailed source info
run_tool subfinder -d target.com -all -json -o /engagement/scans/subdomains.json

# Resolve IPs while enumerating
run_tool subfinder -d target.com -all -silent -nW -oI -o /engagement/scans/subdomains_ips.txt
```

**API keys** enhance results significantly. Configure in `$ENGAGEMENT_DIR/.env`:
```
SUBFINDER_VIRUSTOTAL_API_KEY=...
SUBFINDER_SECURITYTRAILS_API_KEY=...
SUBFINDER_SHODAN_API_KEY=...
```
These are mounted into the container automatically via the .env volume mount.

### 2. DNS Brute-Force with ffuf

Active brute-force for subdomains not found by passive sources:

```bash
# First, baseline — get response size for non-existent subdomain
run_tool curl -s -o /dev/null -w "%{size_download}" -H "Host: nonexistent-xyz.target.com" http://TARGET_IP

# Brute-force with vhost fuzzing
run_tool ffuf -u http://TARGET_IP -H "Host: FUZZ.target.com" \
  -w /seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs <baseline_size> -t 50 \
  -o /engagement/scans/vhost_fuzz.json -of json

# Larger wordlist if initial results are sparse
run_tool ffuf -u http://TARGET_IP -H "Host: FUZZ.target.com" \
  -w /seclists/Discovery/DNS/subdomains-top1million-20000.txt \
  -fs <baseline_size> -t 50 \
  -o /engagement/scans/vhost_fuzz_20k.json -of json
```

### 3. Verify Live Subdomains

```bash
# Check which discovered subdomains resolve and respond
while IFS= read -r sub; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$sub")
  [ "$code" != "000" ] && echo "$sub -> $code"
done < "$ENGAGEMENT_DIR/scans/subdomains.txt"

# Port check on discovered subdomains
run_tool nmap -sV -p 80,443,8080,8443 -iL /engagement/scans/subdomains.txt \
  -oN /engagement/scans/subdomain_ports.txt
```

### 4. Recursive Enumeration

If new subdomains are found, enumerate their subdomains too:

```bash
# Feed discovered subdomains back for deeper enumeration
run_tool subfinder -dL /engagement/scans/subdomains.txt -all -silent \
  -o /engagement/scans/subdomains_recursive.txt
```

### 5. Feed Results into Pipeline

Import discovered subdomains as cases for testing:

```bash
# Convert subdomains to recon_ingest format
while IFS= read -r sub; do
  echo "GET https://$sub"
done < "$ENGAGEMENT_DIR/scans/subdomains.txt" | \
  ./scripts/recon_ingest.sh "$ENGAGEMENT_DIR/cases.db" subdomain-enum
```

## What to Record

- **Total subdomains found** (passive + active)
- **Live subdomains** with HTTP status codes
- **Interesting subdomains**: staging, dev, admin, api, internal, test, beta
- **Services** running on non-standard ports
- **Source** of each subdomain (subfinder source, brute-force, JS reference)
- Any subdomain pointing to **different infrastructure** (cloud, CDN, third-party)
