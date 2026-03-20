---
name: directory-fuzzing
description: Discover hidden directories, files, and endpoints on a web server
origin: RedteamOpencode
---

# Directory Fuzzing

## When to Activate

- Web server identified during recon, need to discover hidden content
- Looking for admin panels, backup files, configuration files
- API endpoint discovery
- After identifying a web application technology (to use targeted wordlists)

## Tools

- `ffuf` — primary fuzzer (fast, flexible)
- `gobuster` — fallback directory bruter
- `curl` — manual verification of findings

## Methodology

### 1. Baseline Response

Before fuzzing, understand how the server handles non-existent paths.

```bash
# Check 404 behavior
curl -s -o /dev/null -w "Code: %{http_code}, Size: %{size_download}" https://TARGET/thispagedoesnotexist12345

# Check if custom 404 returns 200
curl -s https://TARGET/nonexistent_page_xyz | head -20
```

### 2. Common Path Discovery

```bash
# Basic directory scan
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -fc 404

# With auto-calibration to filter noise
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac

# Gobuster fallback
gobuster dir -u https://TARGET -w /usr/share/wordlists/dirb/common.txt -t 50
```

### 3. Extension Fuzzing

```bash
# Common web extensions
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt \
  -e .php,.html,.js,.txt,.bak,.old,.conf,.xml,.json,.yml,.env,.log,.sql,.zip,.tar.gz

# Technology-specific extensions
# PHP: -e .php,.php.bak,.phps,.phtml,.inc
# ASP: -e .asp,.aspx,.config,.ashx,.asmx
# Java: -e .jsp,.do,.action,.html,.xml
```

### 4. Filter Tuning

Reduce noise by filtering on response properties.

```bash
# Filter by status code
ffuf -u https://TARGET/FUZZ -w wordlist.txt -fc 404,403,301

# Filter by response size (exclude default page size)
ffuf -u https://TARGET/FUZZ -w wordlist.txt -fs 1234

# Filter by word count
ffuf -u https://TARGET/FUZZ -w wordlist.txt -fw 42

# Filter by line count
ffuf -u https://TARGET/FUZZ -w wordlist.txt -fl 10

# Match only specific codes (instead of filtering)
ffuf -u https://TARGET/FUZZ -w wordlist.txt -mc 200,301,302,403
```

### 5. Recursive Discovery

Re-run on each discovered directory to find deeper paths.

```bash
# ffuf with recursion depth
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac -recursion -recursion-depth 2

# Manual recursion on interesting finds
ffuf -u https://TARGET/admin/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac
ffuf -u https://TARGET/api/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac
```

### 6. Wordlist Escalation

Start small, go larger on promising targets.

```bash
# Level 1: Quick scan (~4,600 entries)
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirb/common.txt -ac

# Level 2: Medium (~20,000 entries)
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt -ac

# Level 3: Large (~220,000 entries)
ffuf -u https://TARGET/FUZZ -w /usr/share/wordlists/dirbuster/directory-list-2.3-big.txt -ac -t 100

# Specialized lists (SecLists)
# /usr/share/seclists/Discovery/Web-Content/raft-medium-directories.txt
# /usr/share/seclists/Discovery/Web-Content/raft-medium-files.txt
# /usr/share/seclists/Discovery/Web-Content/api/api-endpoints.txt
```

### 7. Backup and Sensitive File Checks

```bash
# Backup file patterns
ffuf -u https://TARGET/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt \
  -e .bak,.old,.orig,.save,.swp,.tmp,~,.copy

# Configuration files
for f in .env .git/config .htaccess web.config wp-config.php .DS_Store Thumbs.db; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://TARGET/$f")
  [ "$code" != "404" ] && echo "$f -> $code"
done

# Source code exposure
curl -s https://TARGET/.git/HEAD
curl -s https://TARGET/.svn/entries | head -5
```

### 8. Virtual Host / Subdomain Fuzzing

```bash
# VHOST discovery
ffuf -u https://TARGET -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt \
  -H "Host: FUZZ.TARGET" -ac

# Filter by response size to remove default vhost response
ffuf -u https://TARGET -w subdomains.txt -H "Host: FUZZ.TARGET" -fs DEFAULT_SIZE
```

### 9. Output and Verification

```bash
# Save results to file
ffuf -u https://TARGET/FUZZ -w wordlist.txt -ac -o results.json -of json

# Verify interesting findings manually
curl -sI https://TARGET/discovered_path
curl -s https://TARGET/discovered_path | head -30
```

## What to Record

- **Discovered paths:** full URL, HTTP status code, response size
- **Interesting files:** backups, configs, source code, logs
- **Admin interfaces:** login pages, management panels
- **API endpoints:** paths that return JSON or structured data
- **Access control gaps:** 403 vs 200 differences, directory listings
- **Technology clues:** file extensions confirm server-side language
- **Follow-up targets:** directories to scan recursively, endpoints to test further
