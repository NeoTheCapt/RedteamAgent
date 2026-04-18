# Wildcard Mode

Use this mode only when the target is a bare domain or contains `*`.

## Phase 0: Enumerate Subdomains

1. Create a parent engagement directory for the wildcard run.
2. Run `subfinder` into `scans/subdomains_raw.txt`.
3. Apply the `subdomain-enumeration` skill's 3-stage filter:
   - DNS resolution
   - web-port reachability
   - lightweight fingerprinting

## Phase 0.5: Prioritize

- **Interactive**: present the prioritized list and wait for approval.
- **Autonomous**: announce the order and start immediately.

Prioritize subdomains with:
- distinct technologies
- exposed admin/auth surfaces
- API endpoints
- unusual ports
- signs of secrets, debug features, or data exposure

## Phase 0.9: Sliding Window

- Process a maximum of `N` subdomains in parallel, default `3`.
- Each subdomain runs the normal 5-phase engagement flow.
- When one subdomain finishes, start the next queued target.
- Never create every child engagement directory up front.

Before starting each child target, run a WAF gate check and skip targets that return `403` together with a clear Cloudflare or CloudFront challenge.

## Final Report

Merge child `findings.md` files into the parent `report.md`.
