# A06:2025 — Insecure Design

- Review authentication flows for logic flaws (skip steps in multi-step processes)
- Test rate limiting on login, registration, and password reset endpoints
- Check for missing account lockout after repeated failed logins
- Look for business logic bypasses (negative quantities, price manipulation, race conditions)
- Test for insecure direct object references in design (not just implementation)
- Verify threat modeling coverage for critical business flows
- Related skills: `auth-bypass`
