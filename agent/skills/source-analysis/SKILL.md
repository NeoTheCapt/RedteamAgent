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
- For binary/image/download artifacts, do not treat "no readable text body" as a reason to return nothing. If the exact asset is still missing or unreadable after that one bounded recovery fetch, classify it from headers, extension, filenames, and byte-size hints; preserve any concrete file-handling/offline-triage implication; still emit a non-empty handoff with explicit `### Case Outcomes`; and do not leave the batch blank.
- Do **not** use the `Read` tool on image/binary attachments themselves during unattended runs. Inspect those artifacts with adjacent textual sidecars (`.headers`, `.body`, batch JSON, crawl metadata) plus `wc -c`, first-byte checks, or tiny `python3` metadata snippets under the engagement workspace. Reserve `Read` for textual files only; otherwise attachment forwarding can fail the handoff before you emit `### Case Outcomes`.
- For concrete client-rendered page cases (`/#/...`, `#/...`, or other fragment routes preserved from bundle analysis), plain HTTP refetch of the same URL is not enough because it only replays the root document. Materialize those cases with `./scripts/katana_route_capture.sh "$DIR" "<exact-case-url>"` and inspect the saved route-capture artifact before marking the route exhausted. If the artifact only contains the exact-route seed error (for example `hybrid: response is nil`) or otherwise has zero successful response rows, treat that as failed materialization and requeue the route instead of closing it.
- If route materialization proves the exact client screen exists (for example a route-specific lazy chunk/module loads, a distinct form/panel renders, or the capture shows a concrete stored/render sink), do **not** close the case just because no brand-new requestable HTTP endpoint appeared. Preserve or requeue the exact route as a live `dynamic_render`/`auth_entry` follow-up and name the concrete UI/render action that still needs to be exercised (for example an exact `./scripts/browser_flow.py --url ... --output-dir ... [--cookies-from-auth "$DIR/auth.json"]` step, plus a tiny `--steps-file` when a specific control/form is already evidenced). If the saved browser-flow summary for that exact route still shows a write-capable DOM (for example multiple text/password/file/range inputs plus a submit/register/send/upload button) but `steps_requested` is `0` or the recorded `steps_run` is passive-only (`wait`, `dump_dom`, `screenshot`) with no typing/click/submit/upload action, that route is still untested: requeue it and name one bounded text-driven mutation attempt using the visible labels/placeholders/button text. If that exact route has already been materialized with route-capture and then covered once with bounded `browser_flow.py`, and the only remaining blocker is missing auth/credentials or a later exploit/surface step that is already preserved as a concrete surface record, do **not** keep requeueing the same source-analysis case just to wait. Mark the queue row exhausted and leave the unresolved work on the tracked `dynamic_render` / `auth_entry` / workflow surface instead; otherwise the dispatcher can starve on the same auth-gated route forever. If saved route-capture/browser-flow evidence already shows a successful write-capable workflow or submission (redirect, success snackbar/toast, confirmation dialog, created record, or another distinct post-submit state), that is still not terminal coverage: keep the exact route/workflow alive for exploit and name one bounded abuse replay on the same workflow (duplicate/second submission first, then one evidence-grounded empty/boundary/forged/unauthorized variant when it fits the visible controls or auth context). When the evidence gives you human-visible cues (button text, field labels, placeholders) but not stable selectors, say so explicitly and prefer text-based browser-flow steps such as `click_text`, `type_by_label`, `type_by_placeholder`, or `submit_first_form` in the follow-up you hand back. For real `<input type=file>` controls, do not use `type`; use selector-aware `upload` with a concrete local file path instead. If a bounded text-helper pass fails on a concrete modal/dialog/site-switch gate OR on a visible form where labels/placeholders/buttons are already evidenced but the helper cannot bind to the real control, inspect the saved DOM or `dom_summary.inputs` once for a stable selector/id/name/aria-label and hand back one selector-aware retry (`wait_for_selector` + exact `click`/`type`/`upload` on that selector) before calling the route blocked, exhausted, or `runtime_error`.
- Keep recovery narrow: exact case URL first, then only directly manifest-linked sibling assets when the manifest/root HTML proves them. Do **not** broaden into fresh crawling, guessed version prefixes, or speculative path construction.
- Do **not** dump or `read` entire large/minified bundles into context. Use targeted searches with strict caps (`grep -n -m`, `sed -n`, `head`, `tail`, `jq`) and keep only the matched lines you need.
- For large local JS/CSS/HTML artifacts, start with `./scripts/source_artifact_summary.py <artifact>` to get a compact bounded summary before any manual regex pass. Reuse that summary instead of reopening the whole file repeatedly.
- If a JS/CSS bundle is large or minified, treat it like an index: extract concrete routes/endpoints/secrets with bounded regex passes instead of broad whole-file scans.
- When a late single-asset batch (especially `javascript`/`stylesheet`) lands after earlier source-analysis already populated `downloads/source-analysis/`, stay scoped to the exact case artifact plus any directly referenced sibling files. Do **not** reopen unrelated root bundles/chunks just because they are present in the workspace.
- If the exact asset is a generic/minified vendor-style bundle or stylesheet and one bounded helper summary plus one targeted search still show no app-specific routes, secrets, or requestable endpoints, mark the case exhausted and move on. Do not keep iterating on the same low-yield static asset.
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
- If source reveals self-assessment or score/progress state endpoints (for example internal challenge, leaderboard, achievement, or scoreboard APIs), treat them as low-signal notes unless they are the only concrete handle on a broader auth/workflow abuse path. Do **not** elevate them into NEW ENDPOINTS just because they are requestable.
- Preserve concrete SPA/hash routes in your structured output. Do **not** collapse them into a generic note like “hidden routes found”. If the bundle reveals a real client-side route (for example a hidden page, admin panel, legal/policy view, review/feedback/cart/register flow, or sandbox screen), keep the exact route string and hand it back as a route/surface candidate.
- When a route is clearly client-rendered rather than a standalone server endpoint, emit it as a `dynamic_render` surface candidate (or `auth_entry` when it is clearly a login/register/auth screen) so surface coverage can materialize a bounded page visit later.
- If the bundle exposes many routes, prioritize breadth across distinct workflow families instead of spending the entire handoff on near-duplicate variants from one subtree. Keep the highest-signal concrete route for each actionable family you see (for example auth entry, privileged/admin, legal/policy/info, feedback/review/cart, sandbox/payment, hidden feature screens) before adding second-order variants from the same family.
- Within one workflow family, do **not** collapse materially different stages into a single representative when they could change the downstream attack plan. If the bundle clearly shows sibling routes for different stages/outcomes (for example login vs register vs forgot-password, browse/list vs submit/review, or end-user flow vs admin/manage), preserve at least one concrete route/surface for each distinct stage instead of treating one sibling as coverage for the rest.
- When source artifacts expose a reusable workflow primitive by itself (for example a captcha helper, reset/setup token flow, TOTP enrollment path, signed-action helper, or other temporary secret source), also preserve at least one concrete consumer workflow route/surface from that same family. Do not hand the primitive off alone if the adjacent route/workflow is visible in the same bundle or artifact set.
- A recovery/auth helper route is not a substitute for a registration/create flow, and a read-only browse route is not a substitute for a write/submit surface when both are concretely visible in the same artifact set.
- When a saved artifact is a downloadable backup, vault, dump, config export, or encoded operational note, do not dismiss it just because the first pass found no plaintext. Preserve the concrete download path, verified file type, and a few candidate seed words from filenames or nearby usernames/emails/brand strings so later exploit work can run a bounded offline triage/cracking step.

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
