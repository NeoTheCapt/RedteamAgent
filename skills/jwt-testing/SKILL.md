---
name: jwt-testing
description: JWT token attack techniques — alg bypass, key confusion, claim tampering
origin: RedteamOpencode
---

# JWT Testing (JSON Web Token Attacks)

## When to Activate

- Application uses JWT for authentication or authorization
- Tokens visible in cookies, Authorization header, or URL params
- Token structure: `xxxxx.yyyyy.zzzzz` (three base64url segments)

## Tools

- jwt_tool (comprehensive JWT testing)
- jwt.io (decode and inspect)
- hashcat (`-m 16500` for JWT cracking)
- john (jwt2john + wordlist)
- Custom scripts for key confusion

## Methodology

### 1. Decode and Analyze

- [ ] Split token: header.payload.signature
- [ ] Base64url-decode header → check `alg`, `typ`, `kid`, `jku`, `jwk`
- [ ] Base64url-decode payload → check `sub`, `role`, `admin`, `exp`, `iat`, `iss`
- [ ] Note expiration time — is it enforced?
- [ ] Collect multiple tokens — compare structure, observe changing fields

### 2. Algorithm None Attack

- [ ] Set header `"alg": "none"` — remove signature
- [ ] Variations: `"alg": "None"`, `"alg": "NONE"`, `"alg": "nOnE"`
- [ ] Empty signature: `header.payload.`
- [ ] Test if server accepts unsigned token

### 3. Weak Secret (HMAC)

- [ ] If `alg: HS256`, brute-force secret:
      `hashcat -m 16500 jwt.txt rockyou.txt`
- [ ] Common secrets: `secret`, `password`, application name, blank string
- [ ] jwt_tool: `python3 jwt_tool.py TOKEN -C -d wordlist.txt`
- [ ] Once secret found, forge arbitrary tokens

### 4. Key Confusion (RS256 → HS256)

- [ ] Obtain public key (JWKS endpoint, TLS cert, `/.well-known/jwks.json`)
- [ ] Change `alg` from `RS256` to `HS256`
- [ ] Sign token with public key as HMAC secret
- [ ] Server may verify HMAC using the public key it already has

### 5. Claim Tampering

- [ ] Change `sub` to another user ID
- [ ] Change `role` from `user` to `admin`
- [ ] Set `admin: true` or `is_admin: 1`
- [ ] Extend `exp` far into the future
- [ ] Change `iss` to see if validated
- [ ] Add unexpected claims the server may process

### 6. Header Injection Attacks

- [ ] `kid` injection: `"kid": "../../dev/null"` (empty key → trivial signature)
- [ ] `kid` SQL injection: `"kid": "key' UNION SELECT 'secret'--"`
- [ ] `jku` spoofing: point to attacker-controlled JWKS
- [ ] `jwk` embedding: include attacker's key in header
- [ ] `x5u` / `x5c`: point to attacker certificate

### 7. Token Lifecycle

- [ ] Use expired token — is expiration enforced?
- [ ] Replay token after logout — is it invalidated?
- [ ] Use token after password change
- [ ] Test token refresh mechanism for flaws
- [ ] Check if tokens are stored and revocable server-side

### 8. Cross-Service Attacks

- [ ] Use token from service A on service B (shared key?)
- [ ] Check audience (`aud`) claim validation
- [ ] Test tokens across environments (staging key on production)

## What to Record

- Token algorithm and claims structure
- Attack type that succeeded (none, weak key, confusion, injection)
- Forged token and the access it granted
- Secret recovered (if HMAC brute-force)
- Severity: Critical (forge any user/admin token) or High (privilege escalation)
- Remediation: strong secrets, enforce algorithm allowlist, validate all claims
