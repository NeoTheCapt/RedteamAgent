---
name: user-enumeration
description: Discover endpoints that leak user existence — registration checks, login errors, password reset, API responses that differ for valid vs invalid users
origin: RedteamOpencode
---

# User Enumeration

## When to Activate

- Login form found (test error messages for valid vs invalid usernames)
- Registration form found (test if "already registered" response differs)
- Password reset / forgot password flow found
- Any API accepting username, email, or phone as input
- OTP / verification code endpoints
- User profile / search APIs

## Tools

- `curl` — craft requests with known-valid vs known-invalid identifiers
- `run_tool ffuf` — brute-force enumeration with wordlists
- `run_tool hydra` — credential stuffing if valid usernames confirmed

## Methodology

### 1. Identify Enumeration Surfaces

Look for any endpoint that accepts a user identifier and returns different responses
for existing vs non-existing users:

```bash
# Common enumeration surfaces to check:
# - POST /login (or /api/login, /auth/login, /api/v1/auth)
# - POST /register (or /signup, /api/register)
# - POST /forgot-password (or /reset-password, /api/password/reset)
# - POST /api/check-email (or /check-username, /check-phone)
# - GET /api/users?email=... (or /api/users/exists)
# - POST /api/otp/send (or /api/verify/send-code)
# - GET /api/profile/<username>
```

### 2. Login Form Enumeration

Test if login error messages distinguish between invalid username and invalid password:

```bash
# Test with definitely-invalid username
curl -s -X POST "http://target/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"definitely_not_a_user_xyz123","password":"wrong"}' \
  -o /tmp/login_invalid_user.txt -w "%{http_code}|%{size_download}"

# Test with likely-valid username (admin, test, user, root)
curl -s -X POST "http://target/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"wrong"}' \
  -o /tmp/login_valid_user.txt -w "%{http_code}|%{size_download}"

# Compare: different status code, response size, error message, or timing?
diff /tmp/login_invalid_user.txt /tmp/login_valid_user.txt
```

Enumeration indicators:
- "User not found" vs "Invalid password" → **enumerable**
- "Invalid credentials" for both → **not enumerable** (good practice)
- Different HTTP status (404 vs 401) → **enumerable**
- Different response size → **enumerable**
- Different response time (valid user takes longer due to password hash check) → **timing-based enumeration**

### 3. Registration Form Enumeration

```bash
# Test with fresh email
curl -s -X POST "http://target/api/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"unique_test_xyz@example.com","password":"Test123!"}' \
  -o /tmp/reg_new.txt -w "%{http_code}|%{size_download}"

# Test with likely-existing email (use found emails from recon, or admin@target.com)
curl -s -X POST "http://target/api/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@target.com","password":"Test123!"}' \
  -o /tmp/reg_existing.txt -w "%{http_code}|%{size_download}"

# Compare responses
diff /tmp/reg_new.txt /tmp/reg_existing.txt
```

Enumeration indicators:
- "Email already registered" vs "Registration successful" → **enumerable**
- "Check your email to verify" for both → **not enumerable**
- Different HTTP status (409 vs 201) → **enumerable**

### 4. Password Reset Enumeration

```bash
# Test with non-existing email
curl -s -X POST "http://target/api/forgot-password" \
  -H "Content-Type: application/json" \
  -d '{"email":"nonexistent_xyz123@example.com"}' \
  -o /tmp/reset_invalid.txt -w "%{http_code}|%{size_download}"

# Test with likely-existing email
curl -s -X POST "http://target/api/forgot-password" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@target.com"}' \
  -o /tmp/reset_valid.txt -w "%{http_code}|%{size_download}"

# Compare
diff /tmp/reset_invalid.txt /tmp/reset_valid.txt
```

### 5. Explicit Check Endpoints

Some apps have dedicated existence-check APIs:

```bash
# Common patterns
for endpoint in "/api/check-email" "/api/check-username" "/api/users/exists" \
  "/api/check-phone" "/api/validate-email" "/api/account/check"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://target$endpoint" \
    -H "Content-Type: application/json" \
    -d '{"email":"test@example.com"}')
  [ "$code" != "404" ] && echo "  $endpoint → $code (exists!)"
done
```

### 6. Timing-Based Enumeration

Even when error messages are identical, response time may differ:

```bash
# Measure response time for invalid vs valid user (run 5x each, compare averages)
echo "=== Invalid user timing ==="
for i in $(seq 1 5); do
  curl -s -X POST "http://target/api/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"nonexistent_xyz","password":"wrong"}' \
    -o /dev/null -w "%{time_total}\n"
done

echo "=== Valid user timing ==="
for i in $(seq 1 5); do
  curl -s -X POST "http://target/api/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"wrong"}' \
    -o /dev/null -w "%{time_total}\n"
done
# If valid user consistently takes 50-200ms longer → timing-based enumeration
```

### 7. Brute-Force Enumeration (after confirming enumerable endpoint)

```bash
# Username enumeration via ffuf
run_tool ffuf -u "http://target/api/login" \
  -X POST -H "Content-Type: application/json" \
  -d '{"username":"FUZZ","password":"invalid"}' \
  -w /seclists/Usernames/top-usernames-shortlist.txt \
  -fr "User not found" \
  -o /engagement/scans/user_enum.json -of json

# Email enumeration via registration check
run_tool ffuf -u "http://target/api/register" \
  -X POST -H "Content-Type: application/json" \
  -d '{"email":"FUZZ@target.com","password":"Test123!"}' \
  -w /seclists/Usernames/top-usernames-shortlist.txt \
  -fr "Check your email" \
  -o /engagement/scans/email_enum.json -of json

# Phone number enumeration (if applicable)
run_tool ffuf -u "http://target/api/check-phone" \
  -X POST -H "Content-Type: application/json" \
  -d '{"phone":"FUZZ"}' \
  -w /engagement/scans/phone_wordlist.txt \
  -fs <baseline_size> \
  -o /engagement/scans/phone_enum.json -of json
```

### 8. OTP / Verification Code Abuse

```bash
# Check if OTP endpoint leaks user existence
curl -s -X POST "http://target/api/otp/send" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+1234567890"}' \
  -o /tmp/otp_invalid.txt -w "%{http_code}|%{size_download}"

curl -s -X POST "http://target/api/otp/send" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+10000000000"}' \
  -o /tmp/otp_valid.txt -w "%{http_code}|%{size_download}"

# Also check: does it rate-limit? Can we enumerate all phone numbers?
```

## What to Record

- **Enumerable endpoint**: exact URL, method, parameter
- **Enumeration type**: error message, status code, response size, or timing
- **Valid vs invalid response**: exact diff
- **Confirmed valid users**: any usernames/emails/phones confirmed to exist
- **Rate limiting**: whether the endpoint has brute-force protection
- **Severity**: MEDIUM if enumerable + no rate limit, LOW if enumerable with rate limit
