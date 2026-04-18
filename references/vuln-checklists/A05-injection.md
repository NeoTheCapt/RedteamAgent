# A05:2025 — Injection

- Test all user inputs for SQL injection (see `sqli-testing` skill)
- Check for OS command injection in parameters that trigger server actions
- Test for XSS in all reflected/stored input contexts (see `xss-testing` skill)
- Test NoSQL injection on MongoDB/document-store backends
- Look for LDAP injection on login forms with directory-backed auth
- Test for template injection (SSTI): `{{7*7}}`, `${7*7}`, `<%= 7*7 %>`
- Test ORM injection and expression language injection
- Fuzz all input vectors: URL params, headers, cookies, JSON/XML bodies
- Related skills: `sqli-testing`, `xss-testing`, `file-inclusion`
