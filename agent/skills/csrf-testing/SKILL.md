---
name: csrf-testing
description: Cross-site request forgery testing for state-changing operations
origin: RedteamOpencode
---

# CSRF Testing (Cross-Site Request Forgery)

## When to Activate

- State-changing operations (POST, PUT, DELETE, PATCH)
- Cookie-based authentication
- Forms or API calls that modify user data, settings, or permissions

## Tools

- curl (manual request replay)
- Burp Suite (generate CSRF PoC)
- Browser DevTools (inspect cookies, headers)
- Custom HTML PoC pages

## Methodology

### 1. Identify CSRF Protections

- [ ] Check for CSRF token in forms (hidden field `csrf_token`, `_token`, `authenticity_token`)
- [ ] Check for CSRF token in headers (`X-CSRF-Token`, `X-XSRF-Token`)
- [ ] Check `SameSite` attribute on session cookies
- [ ] Check `Referer` / `Origin` header validation
- [ ] Check custom headers requirement (e.g., `X-Requested-With`)
- [ ] Check `Content-Type` enforcement (JSON only = partial protection)

### 2. Test Token Validation

- [ ] Remove CSRF token entirely — does request succeed?
- [ ] Submit empty token value
- [ ] Use token from another session / different user
- [ ] Reuse old/expired token
- [ ] Change token to arbitrary value
- [ ] Check if token is tied to session or independent
- [ ] Swap HTTP method: POST → GET (may skip token check)

### 3. Test SameSite Cookie Bypass

- [ ] `SameSite=None` — no protection, full CSRF possible
- [ ] `SameSite=Lax` — test top-level GET navigation (form method=GET)
- [ ] `SameSite=Lax` — 2-minute window after cookie set (Chrome)
- [ ] No SameSite set — defaults vary by browser (Lax in Chrome)
- [ ] Check if API uses cookies at all (vs Bearer tokens)

### 4. Test Referer/Origin Validation

- [ ] Remove `Referer` header entirely (use `<meta name="referrer" content="no-referrer">`)
- [ ] Set Origin to `null` (sandboxed iframe, data: URI)
- [ ] Subdomain spoofing: `https://target.com.attacker.com`
- [ ] Prefix bypass: `https://attacker.com/target.com`
- [ ] Check regex flaws in validation

### 5. Build CSRF PoC

- [ ] Auto-submit form:
      ```html
      <form action="https://target/change-email" method="POST">
        <input name="email" value="attacker@evil.com">
      </form>
      <script>document.forms[0].submit()</script>
      ```
- [ ] Image tag for GET: `<img src="https://target/delete?id=1">`
- [ ] XHR/fetch for JSON APIs (if CORS allows)
- [ ] Multipart form for file upload CSRF

### 6. High-Value Targets

- [ ] Password change (without current password)
- [ ] Email change
- [ ] Account settings modification
- [ ] Admin actions (create user, change roles)
- [ ] Financial transactions
- [ ] API key generation / rotation

### 7. Chained Attacks

- [ ] CSRF + Self-XSS = stored XSS via CSRF
- [ ] CSRF + login = login CSRF (force victim into attacker's account)
- [ ] CSRF + CORS misconfiguration

## What to Record

- Endpoint and action vulnerable to CSRF
- Missing or bypassable protection mechanism
- Working PoC HTML
- Business impact of the forged action
- Severity: Medium (settings change) to High (account takeover, financial)
- Remediation: synchronizer token pattern, SameSite=Strict, Origin validation
