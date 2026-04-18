---
name: web-recon
description: Enumerate web technologies, headers, endpoints, and metadata from a target
origin: RedteamOpencode
---

# Web Reconnaissance

## When to Activate

- Beginning of engagement, new domain/subdomain, need tech stack before deeper testing

## Tools

`run_tool curl`, `run_tool whatweb`, `openssl`, `grep`/`sed`/`jq`

## Methodology

### 1. HTTP Header Analysis
```bash
run_tool curl -sI -L https://TARGET
run_tool curl -sI https://TARGET | grep -iE "^(server|x-powered-by|x-aspnet|x-frame|content-security|strict-transport|set-cookie|www-authenticate)"
run_tool curl -sI -X OPTIONS https://TARGET
```
Note: Server, X-Powered-By, Set-Cookie flags, CSP, missing security headers.

### 2. Technology Fingerprinting
```bash
run_tool whatweb -a 3 https://TARGET
run_tool curl -sL https://TARGET | grep -iE "generator|powered.by|built.with"
run_tool curl -sL https://TARGET | grep -i '<meta' | head -20
```

### 3. CMS Detection
```bash
# WordPress
run_tool curl -s https://TARGET/wp-login.php -o /dev/null -w "%{http_code}"
run_tool curl -s https://TARGET/wp-json/wp/v2/users
# Joomla
run_tool curl -s https://TARGET/administrator/ -o /dev/null -w "%{http_code}"
# Drupal
run_tool curl -s https://TARGET/CHANGELOG.txt | head -5
# Generic
run_tool curl -s https://TARGET/readme.html -o /dev/null -w "%{http_code}"
```

### 4. SSL/TLS Analysis
```bash
echo | openssl s_client -connect TARGET:443 -servername TARGET 2>/dev/null | openssl x509 -noout -text | grep -E "Subject:|Issuer:|Not Before|Not After|DNS:"
for proto in tls1 tls1_1 tls1_2 tls1_3; do
  echo | openssl s_client -connect TARGET:443 -$proto 2>/dev/null | grep -q "Protocol" && echo "$proto: supported"
done
```

### 5. Well-Known Files
```bash
run_tool curl -s https://TARGET/robots.txt
run_tool curl -s https://TARGET/sitemap.xml | head -50
run_tool curl -s https://TARGET/.well-known/security.txt
for path in crossdomain.xml clientaccesspolicy.xml humans.txt .well-known/openid-configuration; do
  code=$(run_tool curl -s -o /dev/null -w "%{http_code}" "https://TARGET/$path")
  [ "$code" != "404" ] && echo "$path -> $code"
done
```

### 6. JS File Extraction (surface-level — deep analysis is source-analyzer's job)
```bash
run_tool curl -sL https://TARGET | grep -oE 'src="[^"]*\.js"' | sed 's/src="//;s/"//'
# Quick grep for API paths and secrets in each JS file
```

Only queue endpoints that are directly requestable and evidenced by a real response or real
HTML/form/link extraction. Directory stems, SPA routes, and guessed names should stay as follow-up
notes or surface candidates, not queue inputs.

### 7. HTML Source (surface-level — deep analysis is source-analyzer's job)
```bash
run_tool curl -sL https://TARGET | grep -oE '<!--.*?-->'                           # Comments
run_tool curl -sL https://TARGET | grep -oiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}'  # Emails
run_tool curl -sL https://TARGET | grep -i 'type="hidden"'                         # Hidden fields
run_tool curl -sL https://TARGET | grep -oE 'href="[^"]*"' | sed 's/href="//;s/"//' | sort -u  # Links
```
