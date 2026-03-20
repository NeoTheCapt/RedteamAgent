# Command: Subdomain Enumeration

The target domain is on the FIRST LINE of this message, after "TARGET_DOMAIN:".
Read it now. Example: `TARGET_DOMAIN: okx.com` means domain is `okx.com`.

If the first line says `TARGET_DOMAIN:` with nothing after it, ask the user for a domain.

## Step 1: Extract Domain

From the TARGET_DOMAIN line at the top:
- Strip scheme (`http://`, `https://`), wildcard (`*.`), trailing path
- Check for `--deep` flag
- Examples: `okx.com` → domain=okx.com | `*.test.com --deep` → domain=test.com, deep=yes

## Step 2: Run subfinder

```bash
ENG_DIR=$(ls -1d engagements/*/ 2>/dev/null | sort -r | head -1 | sed 's|/$||')
if [ -z "$ENG_DIR" ]; then ENG_DIR="$(pwd)"; fi
mkdir -p "$ENG_DIR/scans"
export ENGAGEMENT_DIR="$ENG_DIR"
source scripts/lib/container.sh

run_tool subfinder -d DOMAIN -all -silent -o /engagement/scans/subdomains_raw.txt
echo "Raw: $(wc -l < $ENG_DIR/scans/subdomains_raw.txt) subdomains"
```

Replace DOMAIN with the actual extracted domain.

## Step 3: Verify Live

```bash
> "$ENG_DIR/scans/subdomains_live.txt"
while IFS= read -r sub; do
  code=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "http://$sub" 2>/dev/null)
  [ "$code" != "000" ] && [ -n "$code" ] && echo "$sub $code" >> "$ENG_DIR/scans/subdomains_live.txt"
done < "$ENG_DIR/scans/subdomains_raw.txt"
echo "Live: $(wc -l < $ENG_DIR/scans/subdomains_live.txt)"
```

## Step 4: Deep Mode (only if --deep)

```bash
TARGET_IP=$(/usr/bin/curl -s -o /dev/null -w "%{remote_ip}" "http://DOMAIN" 2>/dev/null)
BASELINE=$(run_tool curl -s -o /dev/null -w "%{size_download}" -H "Host: nonexistent-xyz.DOMAIN" "http://$TARGET_IP")
run_tool ffuf -u "http://$TARGET_IP" -H "Host: FUZZ.DOMAIN" \
  -w /seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -fs "$BASELINE" -t 50 -o /engagement/scans/vhost_fuzz.json -of json
```

## Step 5: Import to Queue (if cases.db exists)

```bash
if [ -f "$ENG_DIR/cases.db" ]; then
  while IFS= read -r line; do
    sub=$(echo "$line" | awk '{print $1}')
    echo "GET https://$sub"
  done < "$ENG_DIR/scans/subdomains_live.txt" | \
    ./scripts/recon_ingest.sh "$ENG_DIR/cases.db" subdomain-enum
fi
```

## Step 6: Display Results

Show live subdomains with HTTP codes. Suggest next steps.
