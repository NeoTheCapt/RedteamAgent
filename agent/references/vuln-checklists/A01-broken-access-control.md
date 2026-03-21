# A01:2025 — Broken Access Control

- Test IDOR by manipulating object IDs in URLs, request bodies, headers
- Attempt privilege escalation: access admin endpoints with low-privilege tokens
- Verify CORS policy: `curl -I -H "Origin: https://evil.com" https://target/api/`
- Test force browsing to authenticated/privileged URLs without credentials
- Check HTTP method tampering (change GET to PUT/DELETE on restricted resources)
- Test JWT tampering: modify claims, use "none" algorithm, forge signatures
- Test parameter tampering: modify user IDs, role fields, permission flags in requests
- Check CSRF protections on state-changing operations
- Related skills: `auth-bypass`
