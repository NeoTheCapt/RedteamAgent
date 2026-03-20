---
name: web-recon
description: Enumerate web technologies, headers, endpoints, and metadata from a target
origin: RedteamOpencode
---

# Web Reconnaissance

## When to Activate

- Beginning of an engagement against a web target
- New domain or subdomain discovered
- Need to identify technology stack before deeper testing
- Pivoting to a new web application within scope

## Tools

- `curl` — HTTP requests, header inspection
- `whatweb` — technology fingerprinting
- `openssl` — SSL/TLS certificate analysis
- Standard text processing (`grep`, `sed`, `jq`)

## Methodology

### 1. HTTP Header Analysis

```bash
# Grab response headers
curl -sI -L https://TARGET

# Check specific security headers
curl -sI https://TARGET | grep -iE "^(server|x-powered-by|x-aspnet|x-frame|content-security|strict-transport|x-content-type|x-xss|set-cookie|www-authenticate)"

# Test HTTP methods
curl -sI -X OPTIONS https://TARGET
```

Key headers to note: `Server`, `X-Powered-By`, `X-AspNet-Version`, `Set-Cookie` (flags, path, domain), `Content-Security-Policy`, missing security headers.

### 2. Technology Fingerprinting

```bash
# Automated fingerprinting
whatweb -a 3 https://TARGET

# Manual checks via response body
curl -sL https://TARGET | grep -iE "generator|powered.by|built.with"

# Check meta tags
curl -sL https://TARGET | grep -i '<meta' | head -20
```

### 3. CMS Detection

```bash
# WordPress
curl -s https://TARGET/wp-login.php -o /dev/null -w "%{http_code}"
curl -s https://TARGET/wp-json/wp/v2/users
curl -s https://TARGET | grep -i "wp-content\|wp-includes"

# Joomla
curl -s https://TARGET/administrator/ -o /dev/null -w "%{http_code}"
curl -s https://TARGET | grep -i "joomla"

# Drupal
curl -s https://TARGET/CHANGELOG.txt | head -5
curl -s https://TARGET | grep -i "drupal"

# Generic CMS indicators
curl -s https://TARGET/readme.html -o /dev/null -w "%{http_code}"
curl -s https://TARGET/license.txt -o /dev/null -w "%{http_code}"
```

### 4. SSL/TLS Analysis

```bash
# Certificate details
echo | openssl s_client -connect TARGET:443 -servername TARGET 2>/dev/null | openssl x509 -noout -text | grep -E "Subject:|Issuer:|Not Before|Not After|DNS:"

# Check supported protocols
for proto in tls1 tls1_1 tls1_2 tls1_3; do
  echo | openssl s_client -connect TARGET:443 -$proto 2>/dev/null | grep -q "Protocol" && echo "$proto: supported"
done

# Check cipher suites
echo | openssl s_client -connect TARGET:443 2>/dev/null | grep "Cipher is"
```

### 5. Well-Known Files

```bash
# robots.txt — discover disallowed paths
curl -s https://TARGET/robots.txt

# Sitemap
curl -s https://TARGET/sitemap.xml | head -50

# Security contact
curl -s https://TARGET/.well-known/security.txt

# Other common files
for path in crossdomain.xml clientaccesspolicy.xml humans.txt .well-known/openid-configuration; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://TARGET/$path")
  [ "$code" != "404" ] && echo "$path -> $code"
done
```

### 6. JavaScript File Analysis (surface-level only)

> **Note:** This is for quick extraction during recon. Deep JS analysis (webpack bundles,
> SPA route extraction, source maps, minified code parsing) is the source-analyzer agent's
> job. Here, just identify JS file URLs and do a quick grep for obvious API paths/secrets.

```bash
# Extract JS file URLs
curl -sL https://TARGET | grep -oE 'src="[^"]*\.js"' | sed 's/src="//;s/"//'

# Search JS files for API endpoints
curl -sL https://TARGET | grep -oE 'src="[^"]*\.js"' | sed 's/src="//;s/"//' | while read js; do
  echo "--- $js ---"
  curl -s "https://TARGET$js" | grep -oE '["'"'"'](/api/[^"'"'"']+)["'"'"']' | sort -u
done

# Look for API keys, tokens, secrets in JS
curl -sL https://TARGET | grep -oE 'src="[^"]*\.js"' | sed 's/src="//;s/"//' | while read js; do
  curl -s "https://TARGET$js" | grep -iE "api[_-]?key|token|secret|password|auth" | head -5
done
```

### 7. HTML Source Analysis (surface-level only)

> **Note:** Quick extraction of obvious items. Deep HTML analysis (data attributes, inline
> config objects, hidden fields analysis) is the source-analyzer agent's job.

```bash
# Extract HTML comments
curl -sL https://TARGET | grep -oE '<!--.*?-->'

# Extract email addresses
curl -sL https://TARGET | grep -oiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}'

# Extract hidden form fields
curl -sL https://TARGET | grep -i 'type="hidden"'

# Extract links (internal and external)
curl -sL https://TARGET | grep -oE 'href="[^"]*"' | sed 's/href="//;s/"//' | sort -u
```

## What to Record

- **Technologies:** web server, language/framework, CMS and version
- **Headers:** server banner, security headers present/missing, cookie flags
- **Endpoints:** paths from robots.txt, sitemap, JS files, HTML links
- **Certificates:** issuer, validity, SANs (may reveal other hostnames)
- **Secrets:** any API keys, tokens, or credentials found in JS/HTML
- **Metadata:** email addresses, HTML comments, hidden fields
- **Anomalies:** unexpected status codes, redirects, error messages
