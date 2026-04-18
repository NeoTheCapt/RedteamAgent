# A02:2025 — Security Misconfiguration

- Scan for default credentials on admin interfaces and services
- Check for verbose error messages leaking stack traces or internal paths
- Test for directory listing: `run_tool curl https://target/images/`
- Check HTTP security headers: `run_tool curl -I https://target/`
- Look for unnecessary features: debug endpoints, sample apps, test accounts
- Check cloud storage permissions (S3 buckets, Azure blobs): `curl https://target.s3.amazonaws.com/`
- Verify cookie flags: `Secure`, `HttpOnly`, `SameSite`
- Test for XML External Entity (XXE) processing
- Check for active debug code or dev tools in production
- Related skills: `web-recon`, `port-scanning`
