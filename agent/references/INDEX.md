# References Index

On-demand reference library. Read specific files when needed — do NOT load everything at once.

## How to Use

1. Check this index to find the relevant reference file
2. Use the listed path under `references/` to load only the specific file you need
3. Example: testing for SQL injection? Read `references/vuln-checklists/A05-injection.md`

---

## vuln-checklists/ — OWASP Top 10:2025

Testing checklists per vulnerability category. Used by: vulnerability-analyst, exploit-developer, operator.

| File | Category |
|------|----------|
| `vuln-checklists/A01-broken-access-control.md` | IDOR, privilege escalation, CORS, CSRF, JWT tampering |
| `vuln-checklists/A02-security-misconfiguration.md` | Default creds, verbose errors, directory listing, missing headers |
| `vuln-checklists/A03-supply-chain-failures.md` | Outdated components, known CVEs, exposed .git, dependency confusion |
| `vuln-checklists/A04-cryptographic-failures.md` | Weak TLS, hardcoded secrets, weak hashing, insecure random |
| `vuln-checklists/A05-injection.md` | SQLi, XSS, command injection, SSTI, NoSQL, LDAP injection |
| `vuln-checklists/A06-insecure-design.md` | Logic flaws, rate limiting, business logic bypass |
| `vuln-checklists/A07-authentication-failures.md` | Credential stuffing, session fixation, MFA bypass, user enumeration |
| `vuln-checklists/A08-integrity-failures.md` | Insecure deserialization, CI/CD exposure, unsigned updates |
| `vuln-checklists/A09-logging-failures.md` | Log injection, missing audit trails (observational) |
| `vuln-checklists/A10-exceptional-conditions.md` | Error disclosure, fail-open, transaction rollback, resource exhaustion |

## api-security/ — OWASP API Security Top 10:2023

API-specific testing checklists. Used by: vulnerability-analyst, exploit-developer.

| File | Category |
|------|----------|
| `api-security/API01-broken-object-level-authz.md` | IDOR on API endpoints |
| `api-security/API02-broken-authentication.md` | Missing auth, token validation flaws |
| `api-security/API03-broken-property-authz.md` | Excessive data exposure, mass assignment |
| `api-security/API04-resource-consumption.md` | Rate limiting, oversized payloads |
| `api-security/API05-broken-function-authz.md` | Admin endpoint access with user tokens |
| `api-security/API06-business-flow-abuse.md` | Missing bot detection on critical flows |
| `api-security/API07-ssrf.md` | SSRF via URL parameters, webhooks |
| `api-security/API08-security-misconfiguration.md` | CORS, debug endpoints, verbose errors |
| `api-security/API09-improper-inventory.md` | Undocumented endpoints, deprecated versions |
| `api-security/API10-unsafe-consumption.md` | SSRF via third-party integrations |

## offensive-tactics/ — Red Team TTPs (from ired.team)

Attack techniques organized by kill chain phase. Used by: operator, exploit-developer, vulnerability-analyst.

### offensive-tactics/initial-access/

| File | Techniques |
|------|-----------|
| `offensive-tactics/initial-access/phishing-macros.md` | VBA macros, DDE, XLM 4.0, remote .dotm template injection |
| `offensive-tactics/initial-access/phishing-vectors.md` | OLE+LNK, HTML forms, SLK files, embedded IE |
| `offensive-tactics/initial-access/credential-harvesting.md` | NetNTLMv2 stealing, OWA spraying, forced auth (.SCF/.URL) |

### offensive-tactics/credential-access/

| File | Techniques |
|------|-----------|
| `offensive-tactics/credential-access/lsass-dumping.md` | mimikatz, procdump, comsvcs.dll, MiniDumpWriteDump |
| `offensive-tactics/credential-access/sam-ntds-dumping.md` | SAM registry dump, NTDS.dit via vssadmin, secretsdump |
| `offensive-tactics/credential-access/credential-theft-misc.md` | LSA secrets, WDigest, DPAPI, registry creds, password filter DLL |

### offensive-tactics/lateral-movement/

| File | Techniques |
|------|-----------|
| `offensive-tactics/lateral-movement/smb-wmi-lateral.md` | PsExec, WMI, WinRM, DCOM, SMB relay |
| `offensive-tactics/lateral-movement/rdp-lateral.md` | RDP hijacking (tscon), SharpRDP headless |
| `offensive-tactics/lateral-movement/tunneling-relaying.md` | SSH tunneling, netcat relay, NTLM relay, port forwarding |

### offensive-tactics/persistence/

| File | Techniques |
|------|-----------|
| `offensive-tactics/persistence/service-persistence.md` | Service DLL, schtasks, BITS jobs |
| `offensive-tactics/persistence/hijacking-persistence.md` | DLL proxying, COM hijacking, .lnk modification |
| `offensive-tactics/persistence/other-persistence.md` | Sticky keys, IFEO, WMI subscriptions, PS profile, Office templates |

### offensive-tactics/privilege-escalation/

| File | Techniques |
|------|-----------|
| `offensive-tactics/privilege-escalation/privesc-windows.md` | DLL hijacking, unquoted paths, weak services, token manipulation, named pipes |

### offensive-tactics/defense-evasion/

| File | Techniques |
|------|-----------|
| `offensive-tactics/defense-evasion/av-edr-bypass.md` | API unhooking, direct syscalls, AV bypass, UPX packing |
| `offensive-tactics/defense-evasion/evasion-techniques.md` | PPID spoofing, timestomping, ADS, Sysmon unloading, PS obfuscation |

### offensive-tactics/code-execution/

| File | Techniques |
|------|-----------|
| `offensive-tactics/code-execution/lolbins-execution.md` | MSBuild, regsvr32, mshta, cmstp, installutil, forfiles |
| `offensive-tactics/code-execution/powershell-bypass.md` | CLM bypass, PowerShdll, AMSI bypass, download cradles |

### offensive-tactics/red-team-infra/

| File | Techniques |
|------|-----------|
| `offensive-tactics/red-team-infra/c2-frameworks.md` | Cobalt Strike, PowerShell Empire, redirectors |
| `offensive-tactics/red-team-infra/infra-setup.md` | Terraform, GoPhish, Modlishka reverse proxy, SMTP |

## active-directory/ — AD & Kerberos Attacks (from ired.team)

Active Directory attack techniques. Used by: exploit-developer, operator.

| File | Techniques |
|------|-----------|
| `active-directory/kerberos-attacks.md` | Kerberoasting, AS-REP roasting, Golden/Silver Tickets, delegation abuse, RBCD |
| `active-directory/ad-enumeration.md` | BloodHound, PowerView, AD module, ACL/ACE abuse |
| `active-directory/ad-persistence.md` | DCSync, DCShadow, AdminSDHolder, shadow credentials, trust abuse |
| `active-directory/adcs-attacks.md` | Certificate template abuse (ESC1), PetitPotam + NTLM relay, Certify/Certipy |

## payloads/ — Attack Payload Library (from PayloadsAllTheThings)

Copy-pasteable payloads organized by attack type. Used by: exploit-developer, vulnerability-analyst, fuzzer.

| File | Category |
|------|----------|
| `payloads/sqli-payloads.md` | UNION, blind, error-based, time-based, WAF bypass, auth bypass per DB type |
| `payloads/nosql-injection-payloads.md` | MongoDB operators ($gt, $ne, $regex, $where), auth bypass, blind extraction |
| `payloads/xss-payloads.md` | DOM XSS, reflected, stored, filter bypass, CSP bypass, polyglots |
| `payloads/ssti-payloads.md` | Per-engine detection and RCE (Jinja2, Twig, Pug, Freemarker, ERB, etc.) |
| `payloads/command-injection-payloads.md` | Blind detection, filter bypass, Linux/Windows, argument injection |
| `payloads/xxe-payloads.md` | File read, OOB/blind XXE, DoS, context-specific (SOAP, SVG, DOCX) |
| `payloads/ssrf-payloads.md` | URL schemas, IP bypass, cloud metadata (AWS/GCP/Azure) |
| `payloads/jwt-payloads.md` | alg:none, key confusion (RS256→HS256), JWK/kid injection, weak secret brute-force |
| `payloads/file-inclusion-payloads.md` | Path traversal, PHP wrappers, null byte, log poisoning, interesting files |
| `payloads/directory-traversal-payloads.md` | Encoding variants, null byte, double URL encoding, OS-specific paths |
| `payloads/upload-payloads.md` | Extension bypass, Content-Type bypass, magic bytes, SVG XSS, zip slip |
| `payloads/deserialization-payloads.md` | Java (ysoserial), PHP, Python (pickle), Node.js, .NET |
| `payloads/cors-payloads.md` | Null origin, subdomain wildcard, pre-flight bypass |
| `payloads/csrf-payloads.md` | Auto-submit forms, JSON CSRF, token bypass techniques |
| `payloads/graphql-payloads.md` | Introspection, batching, field suggestion, injection in variables |
| `payloads/request-smuggling-payloads.md` | CL.TE, TE.CL, TE.TE obfuscation, HTTP/2 downgrade |
| `payloads/race-condition-payloads.md` | HTTP/2 single-packet, limit overrun, multi-endpoint race |
| `payloads/open-redirect-payloads.md` | URL parsing confusion, protocol-relative, unicode normalization |
| `payloads/business-logic-payloads.md` | Negative quantity, coupon abuse, payment bypass, mass assignment |
| `payloads/info-disclosure-probes.md` | Standard endpoints checklist (/metrics, /.env, /actuator, cloud metadata) |

## tools/ — CLI Tool Cheatsheets

Quick-reference per tool, organized by usage phase.

### tools/recon/ — Used by: recon-specialist, operator

| File | Tool |
|------|------|
| `tools/recon/nmap.md` | Port/service discovery and enumeration |
| `tools/recon/whatweb.md` | Web technology fingerprinting |
| `tools/recon/nikto.md` | Web server vulnerability scanning |
| `tools/recon/curl.md` | HTTP request crafting and testing |
| `tools/recon/nuclei.md` | Vulnerability scanning with templates |

### tools/fuzzing/ — Used by: fuzzer, recon-specialist

| File | Tool |
|------|------|
| `tools/fuzzing/ffuf.md` | Web fuzzing (directories, parameters, vhosts) |
| `tools/fuzzing/gobuster.md` | Directory and DNS brute-forcing |
| `tools/fuzzing/wfuzz.md` | Web fuzzing with advanced filtering |
| `tools/fuzzing/dirb.md` | Web directory brute-forcing |

### tools/exploitation/ — Used by: exploit-developer

| File | Tool |
|------|------|
| `tools/exploitation/sqlmap.md` | SQL injection detection and exploitation |
| `tools/exploitation/hydra.md` | Online password brute-forcing |

### tools/cracking/ — Used by: exploit-developer

| File | Tool |
|------|------|
| `tools/cracking/john.md` | Offline password hash cracking (CPU) |
| `tools/cracking/hashcat.md` | Offline password hash cracking (GPU) |

## runtime-guides/ — Shared Runtime References

Shared operator/runtime references. Used by: operator, Claude, Codex.

| File | Purpose |
|------|---------|
| `handoff-protocols.md` | Agent-to-agent handoff rules and expected downstream actions |
| `wildcard-mode.md` | Wildcard target enumeration, prioritization, and sliding-window execution rules |
