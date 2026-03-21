# A08:2025 — Software or Data Integrity Failures

- Check for insecure deserialization in Java/PHP/.NET applications
- Test for unsigned or unverified software updates
- Look for CI/CD pipeline vulnerabilities (publicly accessible build configs)
- Check for auto-update mechanisms without integrity verification
- Test for object injection via serialized data in cookies, parameters, APIs
- Related skills: `file-inclusion` (for deserialization chains), `source-analysis`
