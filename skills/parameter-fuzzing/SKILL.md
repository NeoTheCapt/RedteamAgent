---
name: parameter-fuzzing
description: Discover hidden parameters, test values, and identify input handling anomalies
origin: RedteamOpencode
---

# Parameter Fuzzing

## When to Activate

- Endpoint needs parameter testing or hidden/debug parameter discovery
- IDOR, access control, or logic bug testing via parameter manipulation
- API accepts unknown parameters

## Tools

`run_tool ffuf` (primary), `run_tool curl` (verification), `run_tool arjun` (dedicated param discovery, if available)

## Methodology

### 1. Establish Baseline
```bash
run_tool curl -s -o /dev/null -w "Code: %{http_code}, Size: %{size_download}" https://TARGET/endpoint
```
Record baseline response size for `-fs` filter.

### 2. GET Parameter Discovery
```bash
run_tool ffuf -u "https://TARGET/endpoint?FUZZ=test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt -fs BASELINE_SIZE
# Or with auto-calibration: -ac
```

### 3. POST Parameter Discovery
```bash
# URL-encoded
run_tool ffuf -u "https://TARGET/endpoint" -X POST -d "FUZZ=test" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt -fs BASELINE_SIZE
# JSON
run_tool ffuf -u "https://TARGET/endpoint" -X POST -d '{"FUZZ":"test"}' \
  -H "Content-Type: application/json" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt -fs BASELINE_SIZE
```

### 4. Value Fuzzing
```bash
run_tool ffuf -u "https://TARGET/endpoint?id=FUZZ" -w <(seq 1 1000) -fs BASELINE_SIZE  # IDOR
run_tool ffuf -u "https://TARGET/endpoint?param=FUZZ" -w /usr/share/seclists/Fuzzing/special-chars.txt -fs BASELINE_SIZE
# Boolean/toggle: test true,false,1,0,yes,no,null via loop
# Role values: admin,root,user,guest,superadmin via loop
```

### 5. Header Fuzzing
```bash
run_tool ffuf -u "https://TARGET/endpoint" -H "FUZZ: test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt -fs BASELINE_SIZE
# Common bypass headers:
for header in "X-Forwarded-For: 127.0.0.1" "X-Real-IP: 127.0.0.1" "X-Original-URL: /admin" \
  "X-Debug: true" "X-Debug-Mode: 1" "X-Forwarded-Host: localhost"; do
  run_tool curl -s -o /dev/null -w "%{http_code} %{size_download}" -H "$header" "https://TARGET/endpoint"
done
```

### 6. Cookie Fuzzing
```bash
run_tool ffuf -u "https://TARGET/endpoint" -b "FUZZ=test" \
  -w /usr/share/seclists/Discovery/Web-Content/burp-parameter-names.txt -fs BASELINE_SIZE
```

### 7. Multi-Parameter / Clusterbomb
```bash
run_tool ffuf -u "https://TARGET/endpoint?W1=W2" -w params.txt:W1 -w values.txt:W2 \
  -mode clusterbomb -fs BASELINE_SIZE
```

### 8. Arjun
```bash
run_tool arjun -u "https://TARGET/endpoint" -m GET    # or POST, JSON
run_tool arjun -u "https://TARGET/endpoint" -w custom_params.txt
```

### 9. Verification
```bash
run_tool curl -sv "https://TARGET/endpoint?discovered_param=test" 2>&1
diff <(run_tool curl -s "https://TARGET/endpoint") <(run_tool curl -s "https://TARGET/endpoint?param=value")
```
