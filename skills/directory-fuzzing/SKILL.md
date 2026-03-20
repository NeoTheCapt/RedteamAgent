---
name: directory-fuzzing
description: Discover hidden directories, files, and endpoints on a web server
origin: RedteamOpencode
---

# Directory Fuzzing

## When to Activate

- Web server identified, need hidden content discovery
- Looking for admin panels, backups, configs, API endpoints
- After identifying web technology (for targeted wordlists)

## Tools

`ffuf` (primary), `gobuster` (fallback), `curl` (verification)

## Methodology

### 1. Baseline Response
```bash
curl -s -o /dev/null -w "Code: %{http_code}, Size: %{size_download}" https://TARGET/nonexistent12345
```

### 2. Common Path Discovery
```bash
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -fc 404
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac  # Auto-calibrate
gobuster dir -u https://TARGET -w /usr/share/wordlists/dirb/common.txt -t 50  # Fallback
```

### 3. Extension Fuzzing
```bash
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt \
  -e .php,.html,.js,.txt,.bak,.old,.conf,.xml,.json,.yml,.env,.log,.sql,.zip,.tar.gz
# Tech-specific: PHP(.phps,.phtml,.inc) ASP(.aspx,.config) Java(.jsp,.do,.action)
```

### 4. Filter Tuning
```bash
-fc 404,403,301        # Status code filter
-fs 1234               # Response size filter
-fw 42 / -fl 10        # Word/line count filter
-mc 200,301,302,403    # Match only specific codes
```

### 5. Recursive Discovery
```bash
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac -recursion -recursion-depth 2
ffuf -u https://TARGET/admin/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac
```

### 6. Wordlist Escalation
```bash
# L1: /usr/share/wordlists/dirb/common.txt (~4,600)
# L2: /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt (~20,000)
# L3: /usr/share/wordlists/dirbuster/directory-list-2.3-big.txt (~220,000)
# Specialized: /usr/share/seclists/Discovery/Web-Content/raft-medium-{directories,files}.txt
# API: /usr/share/seclists/Discovery/Web-Content/api/api-endpoints.txt
```

### 7. Backup and Sensitive Files
```bash
ffuf -u https://TARGET/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt \
  -e .bak,.old,.orig,.save,.swp,.tmp,~,.copy
for f in .env .git/config .htaccess web.config wp-config.php .DS_Store; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://TARGET/$f")
  [ "$code" != "404" ] && echo "$f -> $code"
done
curl -s https://TARGET/.git/HEAD
curl -s https://TARGET/.svn/entries | head -5
```

### 8. Virtual Host / Subdomain
```bash
ffuf -u https://TARGET -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -H "Host: FUZZ.TARGET" -ac
```

### 9. Output
```bash
ffuf -u https://TARGET/FUZZ -w wordlist.txt -ac -o results.json -of json
curl -sI https://TARGET/discovered_path  # Verify
```
