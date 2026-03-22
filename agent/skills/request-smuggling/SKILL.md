---
name: request-smuggling
description: HTTP request smuggling via CL.TE/TE.CL desync and cache poisoning
origin: RedteamOpencode
---

# HTTP Request Smuggling Testing

## When to Activate

- Application behind reverse proxy, load balancer, or CDN
- Multiple HTTP servers in request processing chain
- HTTP/1.1 in use between frontend and backend

## Tools

- run_tool curl (raw request crafting)
- Burp Suite Repeater (disable auto content-length update)
- smuggler.py (automated detection)
- HTTP Request Smuggler (Burp extension)
- Custom scripts for precise byte-level control

## Methodology

### 1. Identify Architecture

- [ ] Determine if frontend proxy exists (CDN, load balancer, WAF)
- [ ] Check HTTP version between client→frontend and frontend→backend
- [ ] Identify server software from headers (nginx, Apache, HAProxy, Cloudflare)
- [ ] Note: HTTP/2 downgraded to HTTP/1.1 internally = also vulnerable

### 2. CL.TE Detection (Frontend uses Content-Length, Backend uses Transfer-Encoding)

- [ ] Send request with both CL and TE headers:
      ```
      POST / HTTP/1.1
      Host: target.com
      Content-Length: 6
      Transfer-Encoding: chunked

      0

      G
      ```
- [ ] If next request gets `GPOST` → CL.TE confirmed
- [ ] Time-based: backend waits for more chunked data → timeout difference

### 3. TE.CL Detection (Frontend uses Transfer-Encoding, Backend uses Content-Length)

- [ ] Send:
      ```
      POST / HTTP/1.1
      Host: target.com
      Content-Length: 3
      Transfer-Encoding: chunked

      1
      G
      0

      ```
- [ ] If next request returns unexpected response → TE.CL confirmed
- [ ] Time-based: backend reads CL bytes only, rest poisons next request

### 4. Transfer-Encoding Obfuscation

- [ ] `Transfer-Encoding: chunked` (standard)
- [ ] `Transfer-Encoding : chunked` (space before colon)
- [ ] `Transfer-Encoding: chunked\r\nTransfer-Encoding: x`
- [ ] `Transfer-Encoding: x\r\nTransfer-Encoding: chunked`
- [ ] `Transfer-Encoding:\tchunked` (tab)
- [ ] `Transfer-Encoding: chunked` (extra space)
- [ ] `X: x\r\nTransfer-Encoding: chunked` (header injection)
- [ ] Mixed case: `TrAnSfEr-EnCoDiNg: chunked`
- [ ] Line folding: `Transfer-Encoding:\n chunked`

### 5. Exploitation — Access Control Bypass

- [ ] Smuggle request to internal-only endpoint
- [ ] Access `/admin` path that frontend blocks
- [ ] Bypass IP-based restrictions by smuggling past frontend

### 6. Exploitation — Web Cache Poisoning

- [ ] Smuggle request that poisons cached response
- [ ] Victim receives attacker-controlled content from cache
- [ ] Inject malicious JavaScript via poisoned response

### 7. Exploitation — Credential Theft

- [ ] Smuggle partial request that captures next user's request:
      ```
      POST /store-comment HTTP/1.1
      Content-Length: 400

      comment=
      ```
- [ ] Next user's request (with cookies/auth) appended to comment body
- [ ] Read stolen headers from stored location

### 8. HTTP/2 Specific

- [ ] H2.CL smuggling: HTTP/2 with Content-Length to HTTP/1.1 backend
- [ ] H2.TE smuggling: inject Transfer-Encoding in HTTP/2
- [ ] Request splitting via header injection in HTTP/2 pseudo-headers
- [ ] CRLF injection in HTTP/2 header values

### 9. Validation

- [ ] Confirm desync with timing differential (10+ second difference)
- [ ] Use unique identifiers to track smuggled requests
- [ ] Test multiple times — smuggling can affect other users
- [ ] Be cautious: smuggling is disruptive in shared environments

## What to Record

- Frontend/backend architecture
- Smuggling type: CL.TE, TE.CL, H2.CL, or H2.TE
- Exact request bytes used for detection
- TE obfuscation technique that worked
- Exploitation achieved (access bypass, cache poison, credential theft)
- Severity: Critical (credential theft, cache poisoning) or High (access bypass)
- Remediation: normalize CL/TE handling, use HTTP/2 end-to-end, reject ambiguous requests
