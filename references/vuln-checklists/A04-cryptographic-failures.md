# A04:2025 — Cryptographic Failures

- Check TLS configuration: `nmap --script ssl-enum-ciphers -p 443 target`
- Look for sensitive data in responses (passwords, tokens, PII in plaintext)
- Check for hardcoded secrets in JavaScript source files
- Test for weak hashing (MD5/SHA1) on stored passwords
- Verify data in transit is encrypted (no HTTP fallback for sensitive endpoints)
- Check for insecure random number generation in tokens/session IDs
- Related skills: `source-analysis` (for secrets in JS), `web-recon` (for TLS analysis)
