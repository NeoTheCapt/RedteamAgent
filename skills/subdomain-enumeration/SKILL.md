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

### 3. Verify & Fingerprint Live Subdomains

Collect enough data for prioritization — not just alive/dead, but response characteristics:

```bash
# For each subdomain, collect: status, server, title, size, interesting headers
echo "subdomain|status|server|title|size|notes" > "$ENGAGEMENT_DIR/scans/subdomains_fingerprint.csv"
while IFS= read -r sub; do
  resp=$(/usr/bin/curl -s -o /tmp/sub_resp.html -w "%{http_code}|%{size_download}" \
    -D /tmp/sub_headers.txt --connect-timeout 5 "http://$sub" 2>/dev/null)
  code=$(echo "$resp" | cut -d'|' -f1)
  size=$(echo "$resp" | cut -d'|' -f2)
  [ "$code" = "000" ] && continue
  server=$(grep -i "^server:" /tmp/sub_headers.txt 2>/dev/null | head -1 | cut -d: -f2- | tr -d '\r')
  title=$(grep -oE '<title>[^<]+</title>' /tmp/sub_resp.html 2>/dev/null | head -1 | sed 's/<[^>]*>//g')
  # Collect priority signals
  notes=""
  grep -qi "debug\|x-debug\|x-powered-by\|x-aspnet" /tmp/sub_headers.txt 2>/dev/null && notes="${notes}debug_headers "
  grep -qi "error\|exception\|traceback\|stack.trace" /tmp/sub_resp.html 2>/dev/null && notes="${notes}verbose_errors "
  [ "$code" = "401" ] || [ "$code" = "403" ] && notes="${notes}auth_protected "
  echo "$sub|$code|$server|$title|$size|$notes" >> "$ENGAGEMENT_DIR/scans/subdomains_fingerprint.csv"
  echo "  $sub → $code ($server) [$title] ${notes}"
done < "$ENGAGEMENT_DIR/scans/subdomains.txt"

# Port check on discovered subdomains
run_tool nmap -sV -p 80,443,8080,8443 -iL /engagement/scans/subdomains.txt \
  -oN /engagement/scans/subdomain_ports.txt
```

The fingerprint CSV gives the operator enough data to prioritize:
- **debug_headers**: likely dev/test environment
- **verbose_errors**: misconfigured, easier to exploit
- **auth_protected**: admin panel or internal tool
- **Small response size**: might be API endpoint or minimal app
- **Non-standard server**: unusual tech stack, potentially unpatched

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
