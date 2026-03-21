# A10:2025 — Mishandling of Exceptional Conditions

- Force application errors and examine responses for information disclosure
- Test missing/malformed input handling: empty fields, null values, unexpected types
- Interrupt multi-step transactions at various points to test rollback behavior
- Trigger resource exhaustion scenarios: repeated errors, unclosed connections
- Test error handling consistency across different endpoints
- Check for fail-open conditions: does the app grant access when auth services are down?
- Probe rate limiting on repeated error conditions
- Test null pointer / unexpected return value scenarios
- Related skills: `parameter-fuzzing` (for malformed input testing)
