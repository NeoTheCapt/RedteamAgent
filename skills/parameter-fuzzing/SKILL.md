---
name: parameter-fuzzing
description: Discover hidden parameters, test values, and identify input handling anomalies
origin: RedteamOpencode
---

# Parameter Fuzzing

## When to Activate

- Discovered endpoint needs parameter testing
- Looking for hidden or debug parameters
- Testing for IDOR, access control, or logic bugs via parameter manipulation
- API endpoint accepts unknown parameters
- Need to understand what inputs an endpoint processes

## Tools

- `ffuf` — primary fuzzer for parameter discovery and value testing
- `curl` — manual verification and targeted requests
- `Arjun` — dedicated parameter discovery tool (if available)

## Methodology

### 1. Establish Baseline

Measure the default response to filter noise.

```bash
# GET baseline
curl -s -o /dev/null -w "Code: %{http_code}, Size: %{size_download}, Words: $(curl -s https://TARGET/endpoint | wc -w)" https://TARGET/endpoint

# POST baseline
curl -s -o /dev/null -w "Code: %{http_code}, Size: %{size_download}" -X POST https://TARGET/endpoint
```

Record the baseline response size — use it as the `-fs` filter value.

### 2. GET Parameter Discovery

```bash
# Fuzz parameter names
ffuf -u "https://TARGET/endpoint?FUZZ=test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -fs BASELINE_SIZE

# With auto-calibration
ffuf -u "https://TARGET/endpoint?FUZZ=test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -ac

# Common parameter names (quick check)
ffuf -u "https://TARGET/endpoint?FUZZ=1" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -mc 200 -fs BASELINE_SIZE
```

### 3. POST Parameter Discovery

```bash
# URL-encoded POST body
ffuf -u "https://TARGET/endpoint" \
  -X POST \
  -d "FUZZ=test" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -fs BASELINE_SIZE

# JSON POST body
ffuf -u "https://TARGET/endpoint" \
  -X POST \
  -d '{"FUZZ":"test"}' \
  -H "Content-Type: application/json" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -fs BASELINE_SIZE
```

### 4. Value Fuzzing

Once a parameter is discovered, test interesting values.

```bash
# Numeric IDs (IDOR testing)
ffuf -u "https://TARGET/endpoint?id=FUZZ" \
  -w <(seq 1 1000) \
  -fs BASELINE_SIZE

# Common value payloads
ffuf -u "https://TARGET/endpoint?param=FUZZ" \
  -w /usr/share/seclists/Fuzzing/special-chars.txt \
  -fs BASELINE_SIZE

# Boolean/toggle values
for val in true false 1 0 yes no on off null undefined; do
  echo "=== $val ==="
  curl -s -o /dev/null -w "%{http_code} %{size_download}" "https://TARGET/endpoint?debug=$val"
  echo
done

# Role/privilege values
for val in admin administrator root user guest superadmin; do
  curl -s -o /dev/null -w "$val: %{http_code} %{size_download}\n" "https://TARGET/endpoint?role=$val"
done
```

### 5. Header Fuzzing

```bash
# Custom header discovery
ffuf -u "https://TARGET/endpoint" \
  -H "FUZZ: test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -fs BASELINE_SIZE

# Common debug/bypass headers
for header in "X-Forwarded-For: 127.0.0.1" "X-Real-IP: 127.0.0.1" "X-Original-URL: /admin" \
  "X-Custom-IP-Authorization: 127.0.0.1" "X-Debug: true" "X-Debug-Mode: 1" \
  "Authorization: Bearer null" "X-Forwarded-Host: localhost"; do
  echo "=== $header ==="
  curl -s -o /dev/null -w "%{http_code} %{size_download}" -H "$header" "https://TARGET/endpoint"
  echo
done
```

### 6. Cookie Fuzzing

```bash
# Cookie name discovery
ffuf -u "https://TARGET/endpoint" \
  -b "FUZZ=test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt \
  -fs BASELINE_SIZE

# Cookie value manipulation
ffuf -u "https://TARGET/endpoint" \
  -b "session=FUZZ" \
  -w values.txt \
  -fs BASELINE_SIZE

# Test role/privilege cookies
for val in admin 1 true user root; do
  curl -s -o /dev/null -w "role=$val: %{http_code} %{size_download}\n" \
    -b "role=$val" "https://TARGET/endpoint"
done
```

### 7. Multi-Parameter Testing

```bash
# Two known parameters with one fuzzed
ffuf -u "https://TARGET/endpoint?known=value&FUZZ=test" \
  -w params.txt -fs BASELINE_SIZE

# Clusterbomb mode — fuzz two positions
ffuf -u "https://TARGET/endpoint?W1=W2" \
  -w params.txt:W1 \
  -w values.txt:W2 \
  -mode clusterbomb \
  -fs BASELINE_SIZE
```

### 8. Arjun (Dedicated Parameter Discovery)

```bash
# GET parameter discovery
arjun -u "https://TARGET/endpoint" -m GET

# POST parameter discovery
arjun -u "https://TARGET/endpoint" -m POST

# JSON body
arjun -u "https://TARGET/endpoint" -m JSON

# Custom wordlist
arjun -u "https://TARGET/endpoint" -w custom_params.txt
```

### 9. Verification

```bash
# Confirm discovered parameter with manual request
curl -sv "https://TARGET/endpoint?discovered_param=test" 2>&1

# Compare with and without parameter
diff <(curl -s "https://TARGET/endpoint") <(curl -s "https://TARGET/endpoint?param=value")
```

## What to Record

- **Valid parameters:** name, accepted values, effect on response
- **Hidden/debug parameters:** any debug, test, or admin parameters found
- **IDOR candidates:** parameters that accept numeric IDs or user identifiers
- **Response anomalies:** size changes, status code differences, error messages
- **Access control parameters:** role, admin, debug, or privilege-related params
- **Header-based controls:** headers that change application behavior
- **Follow-up targets:** parameters to test for injection, logic flaws, or authz bypass
