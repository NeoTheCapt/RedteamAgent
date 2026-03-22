# curl

**Purpose:** HTTP request crafting and testing

For live target requests during an engagement, prefer `run_tool curl` instead of raw host `curl`.
`run_tool curl` routes through the engagement-scoped `rtcurl` wrapper, which automatically applies
in-scope auth and the fixed engagement User-Agent. Use raw host `curl` only for external OSINT or
non-target internet resources.

For the current engagement target, use plain `run_tool curl` first. Only add explicit
`Cookie:` or `Authorization:` headers when intentionally testing alternate identities,
session confusion, or auth override behavior.

**Basic GET:** `run_tool curl -v https://target/`
**Headers only:** `run_tool curl -I https://target/`
**POST with data:** `run_tool curl -X POST -d "param=value" https://target/api`
**JSON POST:** `run_tool curl -X POST -H "Content-Type: application/json" -d '{"key":"value"}' https://target/api`
**Follow redirects:** `run_tool curl -L https://target/`
**Explicit cookie override:** `run_tool curl -H "Cookie: session=alternate-user" https://target/`
**Explicit auth override:** `run_tool curl -H "Authorization: Bearer override-token" https://target/api`
**Save output:** `-o output.html`
**Proxy through Burp:** `-x http://127.0.0.1:8080`
