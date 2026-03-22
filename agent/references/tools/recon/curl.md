# curl

**Purpose:** HTTP request crafting and testing

For live target requests during an engagement, prefer `run_tool curl` instead of raw host `curl`.
`run_tool curl` routes through the engagement-scoped `rtcurl` wrapper, which automatically applies
in-scope auth and the fixed engagement User-Agent. Use raw host `curl` only for external OSINT or
non-target internet resources.

**Basic GET:** `curl -v https://target/`
**Headers only:** `curl -I https://target/`
**POST with data:** `curl -X POST -d "param=value" https://target/api`
**JSON POST:** `curl -X POST -H "Content-Type: application/json" -d '{"key":"value"}' https://target/api`
**With cookie:** `curl -b "session=abc123" https://target/`
**Follow redirects:** `curl -L https://target/`
**Custom header:** `curl -H "Authorization: Bearer token" https://target/api`
**Save output:** `-o output.html`
**Proxy through Burp:** `-x http://127.0.0.1:8080`
