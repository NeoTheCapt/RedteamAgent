# Command: Subdomain Enumeration

You are the recon-specialist running subdomain enumeration for a target domain.

## Step 1: Parse Arguments

The user's arguments specify the target domain. Examples:
- `/subdomain test.com`
- `/subdomain test.com --deep` (recursive + brute-force)

Extract the root domain. Strip any scheme (`http://`), wildcard (`*.`), or path.

If no domain provided, check active engagement's scope.json for the target domain.

## Step 2: Run subfinder

```bash
source scripts/lib/container.sh
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
export ENGAGEMENT_DIR="${ENG_DIR:-$(pwd)}"
mkdir -p "$ENGAGEMENT_DIR/scans"

DOMAIN="<parsed domain>"

# Passive enumeration (all sources)
run_tool subfinder -d "$DOMAIN" -all -silent -o /engagement/scans/subdomains_raw.txt
echo "Raw subdomains: $(wc -l < $ENGAGEMENT_DIR/scans/subdomains_raw.txt)"
```

## Step 3: Verify Live Subdomains

```bash
echo "=== Verifying live subdomains ==="
> "$ENGAGEMENT_DIR/scans/subdomains_live.txt"
while IFS= read -r sub; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$sub" 2>/dev/null)
  if [ "$code" != "000" ] && [ -n "$code" ]; then
    echo "$sub ($code)" >> "$ENGAGEMENT_DIR/scans/subdomains_live.txt"
    echo "  [LIVE] $sub → HTTP $code"
  fi
done < "$ENGAGEMENT_DIR/scans/subdomains_raw.txt"
echo ""
echo "Live: $(wc -l < $ENGAGEMENT_DIR/scans/subdomains_live.txt) / Total: $(wc -l < $ENGAGEMENT_DIR/scans/subdomains_raw.txt)"
```

## Step 4: Deep Mode (if --deep flag)

If user specified `--deep`, also run DNS brute-force:

```bash
# Determine target IP for vhost fuzzing
TARGET_IP=$(/usr/bin/curl -s -o /dev/null -w "%{remote_ip}" "http://$DOMAIN" 2>/dev/null)

# Baseline response size
BASELINE=$(run_tool curl -s -o /dev/null -w "%{size_download}" -H "Host: nonexistent-xyz.$DOMAIN" "http://$TARGET_IP")

# Brute-force
run_tool ffuf -u "http://$TARGET_IP" -H "Host: FUZZ.$DOMAIN" \
  -w /seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs "$BASELINE" -t 50 -o /engagement/scans/vhost_fuzz.json -of json

# Merge with subfinder results
jq -r '.results[].host' "$ENGAGEMENT_DIR/scans/vhost_fuzz.json" 2>/dev/null >> "$ENGAGEMENT_DIR/scans/subdomains_raw.txt"
sort -u "$ENGAGEMENT_DIR/scans/subdomains_raw.txt" -o "$ENGAGEMENT_DIR/scans/subdomains_raw.txt"
```

## Step 5: Import into Case Queue (if engagement active)

If an active engagement exists with cases.db:

```bash
if [ -f "$ENGAGEMENT_DIR/cases.db" ]; then
  while IFS= read -r line; do
    sub=$(echo "$line" | awk '{print $1}')
    echo "GET https://$sub"
  done < "$ENGAGEMENT_DIR/scans/subdomains_live.txt" | \
    ./scripts/recon_ingest.sh "$ENGAGEMENT_DIR/cases.db" subdomain-enum
  echo "[subdomain] Imported live subdomains into case queue"
fi
```

## Step 6: Display Results

Present a structured summary:

```
[recon-specialist] Subdomain enumeration complete for <domain>

Found: N total / M live

Live subdomains:
  dev.test.com        (200)
  staging.test.com    (200)
  admin.test.com      (403)
  api.test.com        (200)
  mail.test.com       (302)
  www.test.com        (200)

Saved to: scans/subdomains_live.txt
```

If the engagement is a wildcard engagement, suggest running `/engage` with the results.

## User Arguments

The target domain and flags from the user follows:
