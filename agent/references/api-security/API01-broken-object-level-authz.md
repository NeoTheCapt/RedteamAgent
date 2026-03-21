# API1:2023 — Broken Object Level Authorization

- Test IDOR on every API endpoint that accepts object IDs
- Iterate through IDs: `/api/users/1`, `/api/users/2`, etc.
- Test UUID-based IDs for predictability
- Check both GET and DELETE/PUT with other users' IDs
- Related skills: `auth-bypass`
