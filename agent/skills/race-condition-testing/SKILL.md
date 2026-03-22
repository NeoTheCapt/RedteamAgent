---
name: race-condition-testing
description: Race condition and TOCTOU exploitation — parallel request attacks
origin: RedteamOpencode
---

# Race Condition / TOCTOU Testing

## When to Activate

- Application has single-use actions (coupons, vouchers, invites)
- Financial operations (transfers, purchases, withdrawals)
- Voting, rating, or counting mechanisms
- Inventory or stock management
- Any operation that should execute exactly once

## Tools

- Burp Suite Turbo Intruder
- `run_tool curl --parallel` (HTTP/2 multiplexing)
- Custom Python scripts (asyncio + aiohttp)
- Burp Repeater (send group in parallel)
- GNU parallel

## Methodology

### 1. Identify Race Condition Targets

- [ ] Coupon/promo code redemption
- [ ] Money transfer / payment
- [ ] Gift card activation
- [ ] Vote or like functionality
- [ ] Account creation with unique constraints (email, username)
- [ ] File operations (read-then-write sequences)
- [ ] Inventory purchase (limited stock)
- [ ] Token/OTP validation

### 2. Single-Packet Attack (HTTP/2)

- [ ] Prepare N identical requests
- [ ] Send all in a single TCP packet using HTTP/2 multiplexing:
      ```bash
      run_tool curl --parallel --parallel-max 50 \
        -X POST https://target/redeem-coupon \
        -d "code=DISCOUNT50" \
        -H "Cookie: session=xxx" \
        --url "https://target/redeem-coupon" \
        --url "https://target/redeem-coupon" \
        [repeat N times]
      ```
- [ ] All requests arrive at server simultaneously

### 3. Turbo Intruder Script

- [ ] Use `race-single-packet-attack.py` in Turbo Intruder
- [ ] Configure: capture request, set N copies, send simultaneously
- [ ] Analyze responses: count successes vs expected single success
- [ ] Gate technique: send requests with incomplete body, release all at once

### 4. Limit Overrun Testing

- [ ] Send 20-50 identical requests in parallel
- [ ] Check if action executed more than once
- [ ] Example: redeem coupon 50 times → check if discount applied multiple times
- [ ] Transfer money: send same transfer 20 times → check total deducted vs transferred
- [ ] Vote: send 50 votes → check if count increased by >1

### 5. TOCTOU (Time-of-Check to Time-of-Use)

- [ ] Identify check-then-act sequences:
      1. Server checks balance ≥ amount
      2. Server deducts amount
- [ ] Race between check and deduction = double-spend
- [ ] File access: race between permission check and file read
- [ ] Token validation: race between check and invalidation

### 6. Multi-Endpoint Races

- [ ] Race between different endpoints:
      - Endpoint A: redeem coupon
      - Endpoint B: check coupon status
- [ ] Race between update and read operations
- [ ] Race state changes: apply coupon + checkout simultaneously
- [ ] Session race: change email + password reset at same time

### 7. Partial Construction Race

- [ ] Register user → immediately login before email verification
- [ ] Create object → access before initialization completes
- [ ] Upload file → access before antivirus scan

### 8. Detection Indicators

- [ ] Multiple 200 responses where only one expected
- [ ] Database constraint violations in some responses (duplicate key)
- [ ] Balance or counter inconsistencies after test
- [ ] Some requests succeed, others get 409/500 → partial protection

### 9. Cleanup

- [ ] Verify actual impact: check database state, balances, counts
- [ ] Document exact number of successful duplicate actions
- [ ] Revert test data if possible

## What to Record

- Endpoint and action with race condition
- Number of parallel requests sent
- Number of successful duplicate executions
- Technique used (single-packet, Turbo Intruder, run_tool curl --parallel)
- Business impact (financial loss, integrity violation, privilege escalation)
- Timing window observed
- Severity: High (financial) to Medium (logic bypass)
- Remediation: database locks, idempotency keys, atomic operations, mutex
