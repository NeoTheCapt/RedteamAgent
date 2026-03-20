# API4:2023 — Unrestricted Resource Consumption

- Test rate limiting on all endpoints
- Send oversized payloads, excessive query parameters
- Test pagination limits: request page_size=999999
- Check for missing timeout on long-running operations
- Note: relates to availability, not typically in CTF scope
