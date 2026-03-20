---
name: source-analysis
description: Frontend source code analysis for hidden routes, API endpoints, and secrets
origin: RedteamOpencode
---

# Source Code Analysis

## When to Activate

- After initial recon has identified the target's web pages and JS/CSS files
- When the tech stack includes a SPA framework (React, Vue, Angular)
- When directory fuzzing results are sparse — source analysis often reveals paths fuzzing misses
- When GraphQL or REST API endpoints need schema discovery

## Tools

- `curl` — fetch source files
- `grep` / `sed` / `awk` — pattern extraction
- `jq` — JSON parsing (API schemas, source maps, webpack manifests)
- Standard text processing for minified code analysis

## Division of Labor

This skill is for the **source-analyzer** agent. It handles code-level analysis ONLY.

| Task | Agent |
|------|-------|
| Fetch pages, fingerprint tech, fuzz directories | recon-specialist |
| Analyze fetched HTML/JS/CSS for hidden content | source-analyzer |
| Fuzz discovered parameters | fuzzer |
| Test discovered endpoints for vulns | vulnerability-analyst |

## Methodology

### 1. Identify Source Files

From recon results or by fetching the target's main page:
- List all `<script src="...">` references
- List all `<link rel="stylesheet" href="...">` references
- Check for inline `<script>` blocks with significant content
- Note any source map references (`//# sourceMappingURL=`)

### 2. HTML Analysis

Extract from HTML source:
- All `href`, `src`, `action` attribute values
- Hidden form fields (`<input type="hidden">`)
- Data attributes (`data-url`, `data-api`, `data-endpoint`)
- HTML comments (developer notes, debug paths, TODOs)
- Meta tags (`og:url`, `canonical`, CSRF tokens, API base URLs)
- Inline JS config objects (`window.__CONFIG__`)

### 3. JavaScript Analysis

For each JS file:

**String extraction:**
```bash
curl -sL <js-url> | grep -oE '["'"'"'](/[a-zA-Z0-9_/\-\.]+)["'"'"']' | sort -u
```

**API call patterns:**
- `fetch('/api/...')` / `fetch("/api/...")`
- `axios.get/post/put/delete('/...')`
- `XMLHttpRequest.open('METHOD', '/...')`
- `$.ajax({ url: '/...' })`

**SPA route patterns:**
- React: `<Route path="/..." />`, `path: "/..."`
- Vue: `{ path: '/...', component: ... }`
- Angular: `{ path: '...', component: ... }`

**Secret patterns:**
- `api_key`, `apiKey`, `API_KEY` followed by string literal
- `token`, `secret`, `password`, `auth` assignments
- AWS key patterns: `AKIA[A-Z0-9]{16}`
- JWT tokens: `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`

**Webpack analysis:**
- Find chunk manifest in main bundle
- Extract chunk URLs, fetch and analyze each
- Look for `window.__INITIAL_STATE__` or similar runtime config

### 4. CSS Analysis

Extract from CSS files:
- `url()` references (background images, fonts → reveal directory structure)
- `@import` paths (reveal CSS file organization)
- Source map references (reveal original SCSS/LESS structure)

### 5. API Schema Discovery

Probe for API documentation:
- `/swagger.json`, `/openapi.json`, `/api-docs`, `/v2/api-docs`
- `/graphql` with introspection query
- `/application.wadl`, `?_wadl`
- Parse discovered schemas to enumerate all endpoints and parameters

### 6. Source Map Analysis

If `.map` files are accessible:
- Fetch source map JSON
- Extract `sources` array (reveals original file paths and project structure)
- Reconstruct original source for targeted analysis
- Original source is far more readable than minified bundles

## What to Record

For each finding, note:
- **What**: the endpoint/route/secret found
- **Where**: source file and approximate location
- **How**: the pattern/method that found it
- **Why it matters**: relevance to attack surface (e.g., "unauthenticated admin endpoint")

## Priority Order

1. Secrets and tokens (immediate high-value findings)
2. API endpoints not found by directory fuzzing
3. Frontend routes revealing application structure
4. Hidden form fields and debug endpoints
5. Source maps and debug artifacts
