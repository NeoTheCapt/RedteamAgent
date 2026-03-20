# A03:2025 — Software Supply Chain Failures

- Fingerprint frameworks and library versions: `whatweb target`
- Scan for known CVEs: `nuclei -u https://target -t cves/`
- Check JavaScript libraries for known vulnerabilities via version detection
- Look for outdated server software in response headers
- Inspect package manifests (package.json, requirements.txt) if accessible
- Test for dependency confusion / substitution attack vectors
- Check for exposed .git directories, build configs, CI/CD artifacts
- Related skills: `web-recon`, `source-analysis`
