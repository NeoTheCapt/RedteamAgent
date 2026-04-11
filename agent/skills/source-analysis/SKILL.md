---
name: source-analysis
description: Frontend source code analysis for hidden routes, API endpoints, and secrets
origin: RedteamOpencode
---

# Source Code Analysis

## When to Activate

- After recon identifies target's web pages and JS/CSS files
- SPA framework detected (React, Vue, Angular)
- Directory fuzzing sparse — source analysis reveals paths fuzzing misses
- GraphQL/REST API schema discovery needed

## Tools

`run_tool curl`, `grep`/`sed`/`awk`, `jq`

## Local Artifact Guardrails

When the task already provides a saved batch file or engagement workspace artifacts, prefer the local files over re-fetching remote content.

- Start from the saved batch file, then inspect only the directly linked local artifacts you actually need.
- For `page` batches, read the saved HTML/headers first, then only the specific JS/CSS files referenced by that page.
- If a saved case or adjacent crawl metadata shows a concrete in-scope asset returned successfully but the engagement-local body is missing or empty, do one bounded recovery fetch of that exact URL back into the engagement workspace before declaring the case unanalyzable.
- For concrete client-rendered page cases (`/#/...`, `#/...`, or other fragment routes preserved from bundle analysis), plain HTTP refetch of the same URL is not enough because it only replays the root document. Materialize those cases with `./scripts/katana_route_capture.sh "$DIR" "<exact-case-url>"` and inspect the saved route-capture artifact before marking the route exhausted. If the artifact only contains the exact-route seed error (for example `hybrid: response is nil`) or otherwise has zero successful response rows, treat that as failed materialization and requeue the route instead of closing it.
- Keep recovery narrow: exact case URL first, then only directly manifest-linked sibling assets when the manifest/root HTML proves them. Do **not** broaden into fresh crawling, guessed version prefixes, or speculative path construction.
- Do **not** dump or `read` entire large/minified bundles into context. Use targeted searches with strict caps (`grep -n -m`, `sed -n`, `head`, `tail`, `jq`) and keep only the matched lines you need.
- If a JS/CSS bundle is large or minified, treat it like an index: extract concrete routes/endpoints/secrets with bounded regex passes instead of broad whole-file scans.
- When a saved manifest (`asset-manifest.json`, chunk map, preload map, SSR config) lists JS/CSS asset paths, preserve the manifest path exactly as written unless the file itself proves a different absolute base. Do **not** prepend nearby version directories, CDN prefixes, or guessed parent paths just because adjacent config exposes a `versionUrls` map.
- If a fetched `.js`/`.css`/`.json` artifact contains XML/HTML object-storage errors such as `NoSuchKey`, `AccessDenied`, or SPA fallback markup, treat that as a retrieval-path problem rather than real source content. Reconstruct follow-up URLs from the manifest/root HTML exactly, prefer relative-path joins over guessed version prefixes, and clearly mark stale placeholder artifacts as exhausted.
- Avoid the `file` utility in runtime containers; rely on headers, file extensions, `wc -c`, or tiny Python snippets if you need type/size hints.
- Stop after a few bounded passes per artifact and return concise structured results. Do not spend the whole task spelunking one huge bundle.

## Division of Labor

| Task | Agent |
|------|-------|
| Fetch pages, fingerprint, fuzz dirs | recon-specialist |
| Analyze HTML/JS/CSS for hidden content | source-analyzer |
| Fuzz discovered params | fuzzer |
| Test endpoints for vulns | vulnerability-analyst |

## Methodology

### 1. Identify Source Files
List `<script src>`, `<link stylesheet href>`, inline `<script>` blocks, source map refs.

### 2. HTML Analysis
Extract: href/src/action values, hidden fields, data-url/data-api attributes,
HTML comments, meta tags (canonical, CSRF, API base), inline config (`window.__CONFIG__`).

### 3. JavaScript Analysis
```bash
run_tool curl -sL <js-url> | grep -oE '["'"'"'](/[a-zA-Z0-9_/\-\.]+)["'"'"']' | sort -u
```
For saved local bundles, prefer bounded pattern extraction over full reads, for example:
```bash
grep -n -m 80 -E 'fetch\(|axios\.|XMLHttpRequest|\.open\(|/rest/|/api/|/#/' downloads/main.js
```
- API calls: `fetch()`, axios, XHR, `$.ajax` patterns
- SPA routes: React `path="/..."`, Vue `{ path: }`, Angular `{ path: }`
- Secrets: `api_key`, `token`, `secret`, `password` assignments; AWS `AKIA[A-Z0-9]{16}`; JWT `eyJ...`
- Webpack: chunk manifest, chunk URLs, `window.__INITIAL_STATE__`
- When matches explode because of minified code, narrow the regex and rerun instead of accepting giant output
- Preserve concrete SPA/hash routes in your structured output. Do **not** collapse them into a generic note like “hidden routes found”. If the bundle reveals a real client-side route (for example a hidden page, admin panel, legal/policy view, review/feedback/cart/register flow, or sandbox screen), keep the exact route string and hand it back as a route/surface candidate.
- When a route is clearly client-rendered rather than a standalone server endpoint, emit it as a `dynamic_render` surface candidate (or `auth_entry` when it is clearly a login/register/auth screen) so surface coverage can materialize a bounded page visit later.
- If the bundle exposes many routes, prioritize breadth across distinct workflow families instead of spending the entire handoff on near-duplicate variants from one subtree. Keep the highest-signal concrete route for each actionable family you see (for example auth entry, privileged/admin, legal/policy/info, feedback/review/cart, sandbox/payment, hidden feature screens) before adding second-order variants from the same family.

### 4. CSS Analysis
Extract `url()` refs, `@import` paths, source map refs.

### 5. API Schema Discovery
Probe: /swagger.json, /openapi.json, /api-docs, /graphql (introspection), /application.wadl

If an OpenAPI / Swagger spec is accessible, ingest it into the queue instead of leaving it as
a passive note:

```bash
run_tool curl -sL "https://TARGET/openapi.json" -o $DIR/scans/openapi.json
./scripts/spec_ingest.sh "$ENGAGEMENT_DIR/cases.db" "$ENGAGEMENT_DIR/scans/openapi.json"
./scripts/dispatcher.sh "$ENGAGEMENT_DIR/cases.db" stats
```

This creates `api-spec` cases that should stay with `source-analyzer` long enough to resolve docs/spec carriers into concrete API cases for `vulnerability-analyst`.

### 6. Source Map Analysis
Fetch `.map` only when there is an explicit source map reference or saved map artifact. Do not brute-force nonexistent maps.

When a map exists, extract just the `sources` array and the specific source files needed for the case at hand instead of dumping the whole map.

## Priority Order

1. Secrets and tokens (immediate high-value)
2. API endpoints not found by fuzzing
3. Frontend routes revealing app structure
4. Hidden form fields and debug endpoints
5. Source maps and debug artifacts
