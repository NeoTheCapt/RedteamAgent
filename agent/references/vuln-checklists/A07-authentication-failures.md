# A07:2025 — Authentication Failures

- Test for credential stuffing (no rate limiting or CAPTCHA on login)
- Check password policy enforcement (weak passwords accepted)
- Test session fixation: does the session ID change after login?
- Look for session tokens in URLs or logs
- Verify logout actually invalidates the session server-side
- Test multi-factor authentication bypass techniques
- Check for user enumeration via login/registration/reset responses
- Test password reset flow for token predictability, lack of expiry
- Related skills: `auth-bypass`
