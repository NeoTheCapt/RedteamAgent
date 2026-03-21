# References Index

On-demand reference library. Read specific files when needed — do NOT load everything at once.

## How to Use

1. Check this index to find the relevant reference file
2. Use the Read tool to load only the specific file you need
3. Example: testing for SQL injection? Read `references/vuln-checklists/A05-injection.md`

---

## vuln-checklists/ — OWASP Top 10:2025

Testing checklists per vulnerability category. Used by: vulnerability-analyst, exploit-developer, operator.

| File | Category |
|------|----------|
| `A01-broken-access-control.md` | IDOR, privilege escalation, CORS, CSRF, JWT tampering |
| `A02-security-misconfiguration.md` | Default creds, verbose errors, directory listing, missing headers |
| `A03-supply-chain-failures.md` | Outdated components, known CVEs, exposed .git, dependency confusion |
| `A04-cryptographic-failures.md` | Weak TLS, hardcoded secrets, weak hashing, insecure random |
| `A05-injection.md` | SQLi, XSS, command injection, SSTI, NoSQL, LDAP injection |
| `A06-insecure-design.md` | Logic flaws, rate limiting, business logic bypass |
| `A07-authentication-failures.md` | Credential stuffing, session fixation, MFA bypass, user enumeration |
| `A08-integrity-failures.md` | Insecure deserialization, CI/CD exposure, unsigned updates |
| `A09-logging-failures.md` | Log injection, missing audit trails (observational) |
| `A10-exceptional-conditions.md` | Error disclosure, fail-open, transaction rollback, resource exhaustion |

## api-security/ — OWASP API Security Top 10:2023

API-specific testing checklists. Used by: vulnerability-analyst, exploit-developer.

| File | Category |
|------|----------|
| `API01-broken-object-level-authz.md` | IDOR on API endpoints |
| `API02-broken-authentication.md` | Missing auth, token validation flaws |
| `API03-broken-property-authz.md` | Excessive data exposure, mass assignment |
| `API04-resource-consumption.md` | Rate limiting, oversized payloads |
| `API05-broken-function-authz.md` | Admin endpoint access with user tokens |
| `API06-business-flow-abuse.md` | Missing bot detection on critical flows |
| `API07-ssrf.md` | SSRF via URL parameters, webhooks |
| `API08-security-misconfiguration.md` | CORS, debug endpoints, verbose errors |
| `API09-improper-inventory.md` | Undocumented endpoints, deprecated versions |
| `API10-unsafe-consumption.md` | SSRF via third-party integrations |

## offensive-tactics/ — Red Team TTPs (from ired.team)

Attack techniques organized by kill chain phase. Used by: operator, exploit-developer, vulnerability-analyst.

### offensive-tactics/initial-access/

| File | Techniques |
|------|-----------|
| `phishing-macros.md` | VBA macros, DDE, XLM 4.0, remote .dotm template injection |
| `phishing-vectors.md` | OLE+LNK, HTML forms, SLK files, embedded IE |
| `credential-harvesting.md` | NetNTLMv2 stealing, OWA spraying, forced auth (.SCF/.URL) |

### offensive-tactics/credential-access/

| File | Techniques |
|------|-----------|
| `lsass-dumping.md` | mimikatz, procdump, comsvcs.dll, MiniDumpWriteDump |
| `sam-ntds-dumping.md` | SAM registry dump, NTDS.dit via vssadmin, secretsdump |
| `credential-theft-misc.md` | LSA secrets, WDigest, DPAPI, registry creds, password filter DLL |

### offensive-tactics/lateral-movement/

| File | Techniques |
|------|-----------|
| `smb-wmi-lateral.md` | PsExec, WMI, WinRM, DCOM, SMB relay |
| `rdp-lateral.md` | RDP hijacking (tscon), SharpRDP headless |
| `tunneling-relaying.md` | SSH tunneling, netcat relay, NTLM relay, port forwarding |

### offensive-tactics/persistence/

| File | Techniques |
|------|-----------|
| `service-persistence.md` | Service DLL, schtasks, BITS jobs |
| `hijacking-persistence.md` | DLL proxying, COM hijacking, .lnk modification |
| `other-persistence.md` | Sticky keys, IFEO, WMI subscriptions, PS profile, Office templates |

### offensive-tactics/privilege-escalation/

| File | Techniques |
|------|-----------|
| `privesc-windows.md` | DLL hijacking, unquoted paths, weak services, token manipulation, named pipes |

### offensive-tactics/defense-evasion/

| File | Techniques |
|------|-----------|
| `av-edr-bypass.md` | API unhooking, direct syscalls, AV bypass, UPX packing |
| `evasion-techniques.md` | PPID spoofing, timestomping, ADS, Sysmon unloading, PS obfuscation |

### offensive-tactics/code-execution/

| File | Techniques |
|------|-----------|
| `lolbins-execution.md` | MSBuild, regsvr32, mshta, cmstp, installutil, forfiles |
| `powershell-bypass.md` | CLM bypass, PowerShdll, AMSI bypass, download cradles |

### offensive-tactics/red-team-infra/

| File | Techniques |
|------|-----------|
| `c2-frameworks.md` | Cobalt Strike, PowerShell Empire, redirectors |
| `infra-setup.md` | Terraform, GoPhish, Modlishka reverse proxy, SMTP |

## active-directory/ — AD & Kerberos Attacks (from ired.team)

Active Directory attack techniques. Used by: exploit-developer, operator.

| File | Techniques |
|------|-----------|
| `kerberos-attacks.md` | Kerberoasting, AS-REP roasting, Golden/Silver Tickets, delegation abuse, RBCD |
| `ad-enumeration.md` | BloodHound, PowerView, AD module, ACL/ACE abuse |
| `ad-persistence.md` | DCSync, DCShadow, AdminSDHolder, shadow credentials, trust abuse |
| `adcs-attacks.md` | Certificate template abuse (ESC1), PetitPotam + NTLM relay, Certify/Certipy |

## payloads/ — Attack Payload Library (from PayloadsAllTheThings)

Copy-pasteable payloads organized by attack type. Used by: exploit-developer, vulnerability-analyst, fuzzer.

| File | Category |
|------|----------|
| `sqli-payloads.md` | UNION, blind, error-based, time-based, WAF bypass, auth bypass per DB type |
| `nosql-injection-payloads.md` | MongoDB operators ($gt, $ne, $regex, $where), auth bypass, blind extraction |
| `xss-payloads.md` | DOM XSS, reflected, stored, filter bypass, CSP bypass, polyglots |
| `ssti-payloads.md` | Per-engine detection and RCE (Jinja2, Twig, Pug, Freemarker, ERB, etc.) |
| `command-injection-payloads.md` | Blind detection, filter bypass, Linux/Windows, argument injection |
| `xxe-payloads.md` | File read, OOB/blind XXE, DoS, context-specific (SOAP, SVG, DOCX) |
| `ssrf-payloads.md` | URL schemas, IP bypass, cloud metadata (AWS/GCP/Azure) |
| `jwt-payloads.md` | alg:none, key confusion (RS256→HS256), JWK/kid injection, weak secret brute-force |
| `file-inclusion-payloads.md` | Path traversal, PHP wrappers, null byte, log poisoning, interesting files |
| `directory-traversal-payloads.md` | Encoding variants, null byte, double URL encoding, OS-specific paths |
| `upload-payloads.md` | Extension bypass, Content-Type bypass, magic bytes, SVG XSS, zip slip |
| `deserialization-payloads.md` | Java (ysoserial), PHP, Python (pickle), Node.js, .NET |
| `cors-payloads.md` | Null origin, subdomain wildcard, pre-flight bypass |
| `csrf-payloads.md` | Auto-submit forms, JSON CSRF, token bypass techniques |
| `graphql-payloads.md` | Introspection, batching, field suggestion, injection in variables |
| `request-smuggling-payloads.md` | CL.TE, TE.CL, TE.TE obfuscation, HTTP/2 downgrade |
| `race-condition-payloads.md` | HTTP/2 single-packet, limit overrun, multi-endpoint race |
| `open-redirect-payloads.md` | URL parsing confusion, protocol-relative, unicode normalization |
| `business-logic-payloads.md` | Negative quantity, coupon abuse, payment bypass, mass assignment |
| `info-disclosure-probes.md` | Standard endpoints checklist (/metrics, /.env, /actuator, cloud metadata) |

## tools/ — CLI Tool Cheatsheets

Quick-reference per tool, organized by usage phase.

### tools/recon/ — Used by: recon-specialist, operator

| File | Tool |
|------|------|
| `nmap.md` | Port/service discovery and enumeration |
| `whatweb.md` | Web technology fingerprinting |
| `nikto.md` | Web server vulnerability scanning |
| `curl.md` | HTTP request crafting and testing |
| `nuclei.md` | Vulnerability scanning with templates |

### tools/fuzzing/ — Used by: fuzzer, recon-specialist

| File | Tool |
|------|------|
| `ffuf.md` | Web fuzzing (directories, parameters, vhosts) |
| `gobuster.md` | Directory and DNS brute-forcing |
| `wfuzz.md` | Web fuzzing with advanced filtering |
| `dirb.md` | Web directory brute-forcing |

### tools/exploitation/ — Used by: exploit-developer

| File | Tool |
|------|------|
| `sqlmap.md` | SQL injection detection and exploitation |
| `hydra.md` | Online password brute-forcing |

### tools/cracking/ — Used by: exploit-developer

| File | Tool |
|------|------|
| `john.md` | Offline password hash cracking (CPU) |
| `hashcat.md` | Offline password hash cracking (GPU) |
