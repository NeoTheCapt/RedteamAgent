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

### 3. Filter, Verify & Fingerprint Subdomains

Three-stage filter: DNS resolution → web port open → fingerprint. Only subdomains that
pass ALL stages enter the engagement pipeline.

```bash
# Stage 1: DNS resolution filter — drop subdomains that don't resolve
> "$ENGAGEMENT_DIR/scans/subdomains_resolved.txt"
while IFS= read -r sub; do
  ip=$(dig +short "$sub" 2>/dev/null | head -1)
  if [ -n "$ip" ] && [ "$ip" != ";;" ]; then
    echo "$sub" >> "$ENGAGEMENT_DIR/scans/subdomains_resolved.txt"
  else
    echo "  [SKIP] $sub — DNS does not resolve"
  fi
done < "$ENGAGEMENT_DIR/scans/subdomains.txt"
echo "Resolved: $(wc -l < $ENGAGEMENT_DIR/scans/subdomains_resolved.txt) / $(wc -l < $ENGAGEMENT_DIR/scans/subdomains.txt)"

# Stage 2: Web port check — try HTTP (80), HTTPS (443), then common alt ports (8080, 8443)
> "$ENGAGEMENT_DIR/scans/subdomains_live.txt"
while IFS= read -r sub; do
  live=""
  for proto_port in "http://$sub" "https://$sub" "http://$sub:8080" "https://$sub:8443"; do
    code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 -k "$proto_port" 2>/dev/null)
    if [ "$code" != "000" ] && [ -n "$code" ]; then
      echo "$sub $proto_port $code" >> "$ENGAGEMENT_DIR/scans/subdomains_live.txt"
      live="yes"
      break
    fi
  done
  [ -z "$live" ] && echo "  [SKIP] $sub — no open web port (80/443/8080/8443)"
done < "$ENGAGEMENT_DIR/scans/subdomains_resolved.txt"
echo "Live web: $(wc -l < $ENGAGEMENT_DIR/scans/subdomains_live.txt)"

# Stage 3: Fingerprint live subdomains for prioritization
echo "subdomain|url|status|server|title|size|notes" > "$ENGAGEMENT_DIR/scans/subdomains_fingerprint.csv"
while IFS=' ' read -r sub url code; do
  resp=$(/usr/bin/curl -s -o /tmp/sub_resp.html -w "%{size_download}" \
    -D /tmp/sub_headers.txt --connect-timeout 5 -k "$url" 2>/dev/null)
  size="$resp"
  server=$(grep -i "^server:" /tmp/sub_headers.txt 2>/dev/null | head -1 | cut -d: -f2- | tr -d '\r')
  title=$(grep -oE '<title>[^<]+</title>' /tmp/sub_resp.html 2>/dev/null | head -1 | sed 's/<[^>]*>//g')
  notes=""
  grep -qi "debug\|x-debug\|x-powered-by\|x-aspnet" /tmp/sub_headers.txt 2>/dev/null && notes="${notes}debug_headers "
  grep -qi "error\|exception\|traceback\|stack.trace" /tmp/sub_resp.html 2>/dev/null && notes="${notes}verbose_errors "
  [ "$code" = "401" ] || [ "$code" = "403" ] && notes="${notes}auth_protected "
  echo "$sub|$url|$code|$server|$title|$size|$notes" >> "$ENGAGEMENT_DIR/scans/subdomains_fingerprint.csv"
  echo "  $sub → $code ($server) [$title] ${notes}"
done < "$ENGAGEMENT_DIR/scans/subdomains_live.txt"
```

**Filter summary**: Only subdomains in `subdomains_fingerprint.csv` should enter engagements.
Subdomains that fail DNS or have no web port are logged and skipped — do NOT create
engagements for them.

Fingerprint signals for prioritization:
- **debug_headers**: likely dev/test environment → HIGH priority
- **verbose_errors**: misconfigured → HIGH priority
- **auth_protected**: admin panel or internal tool → test for bypass
- **Small response size**: minimal app or API → less hardened
- **Non-standard server**: unusual tech, potentially unpatched

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
