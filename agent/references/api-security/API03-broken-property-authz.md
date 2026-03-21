# API3:2023 — Broken Object Property Level Authorization

- Check for excessive data exposure: does the API return more fields than the UI shows?
- Test mass assignment: add extra fields in PUT/PATCH requests (e.g., `"role": "admin"`)
- Compare API response fields with what the frontend actually uses
- Related skills: `auth-bypass`, `parameter-fuzzing`
