# Command: Subdomain Enumeration

You are the recon-specialist running subdomain enumeration.

## IMPORTANT: Read Your Arguments

The user's target domain is appended at the VERY END of this message (after "## User Arguments").
Look there FIRST. It will be something like `okx.com` or `test.com --deep`.

If you see a domain there, use it. Do NOT say "no domain provided" if there is text after "## User Arguments".

## Step 1: Extract Domain

From the user arguments at the end of this message:
1. Take the first word as the domain (e.g., `okx.com`)
2. Strip any scheme (`http://`, `https://`), wildcard (`*.`), or trailing path (`/`)
3. Check for `--deep` flag

Examples:
- `okx.com` → domain=`okx.com`, deep=no
- `https://test.com --deep` → domain=`test.com`, deep=yes
- `*.example.org` → domain=`example.org`, deep=no

If truly no text after "## User Arguments", THEN check active engagement scope.json.

## Step 2: Setup

```bash
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
if [ -z "$ENG_DIR" ]; then
  ENG_DIR="$(pwd)"
fi
mkdir -p "$ENG_DIR/scans"
export ENGAGEMENT_DIR="$ENG_DIR"
source scripts/lib/container.sh
```

## Step 3: Run subfinder

Replace DOMAIN below with the actual domain you extracted in Step 1.

```bash
run_tool subfinder -d DOMAIN -all -silent -o /engagement/scans/subdomains_raw.txt
echo "Raw: $(wc -l < $ENG_DIR/scans/subdomains_raw.txt) subdomains"
```

## Step 4: Verify Live Subdomains

```bash
> "$ENG_DIR/scans/subdomains_live.txt"
while IFS= read -r sub; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$sub" 2>/dev/null)
  if [ "$code" != "000" ] && [ -n "$code" ]; then
    echo "$sub $code" >> "$ENG_DIR/scans/subdomains_live.txt"
  fi
done < "$ENG_DIR/scans/subdomains_raw.txt"
echo "Live: $(wc -l < $ENG_DIR/scans/subdomains_live.txt)"
```

## Step 5: Deep Mode (only if --deep flag present)

```bash
TARGET_IP=$(/usr/bin/curl -s -o /dev/null -w "%{remote_ip}" "http://DOMAIN" 2>/dev/null)
BASELINE=$(run_tool curl -s -o /dev/null -w "%{size_download}" -H "Host: nonexistent-xyz.DOMAIN" "http://$TARGET_IP")
run_tool ffuf -u "http://$TARGET_IP" -H "Host: FUZZ.DOMAIN" \
  -w /seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs "$BASELINE" -t 50 -o /engagement/scans/vhost_fuzz.json -of json
```

## Step 6: Import to Queue (if cases.db exists)

```bash
if [ -f "$ENG_DIR/cases.db" ]; then
  while IFS= read -r line; do
    sub=$(echo "$line" | awk '{print $1}')
    echo "GET https://$sub"
  done < "$ENG_DIR/scans/subdomains_live.txt" | \
    ./scripts/recon_ingest.sh "$ENG_DIR/cases.db" subdomain-enum
fi
```

## Step 7: Display Results

Show the live subdomains with HTTP status codes. Suggest next steps.

## User Arguments

