---
name: port-scanning
description: Discover open ports, running services, and their versions on a target
origin: RedteamOpencode
---

# Port Scanning

## When to Activate

- Initial recon of new target, need to discover services before vuln testing
- Verifying firewall rules, new IP discovered

## Tools

`nmap` (primary), `nc` (quick checks/banner grab)

## Methodology

### 1. Quick Initial Scan
```bash
nmap -sV -sC -T4 TARGET -oA nmap_initial
```

### 2. Full TCP Scan
```bash
nmap -sV -sC -T4 -p- TARGET -oN nmap_full_tcp.txt
# Speed optimization: discover ports first, then deep scan
nmap -sS -T4 -p- --min-rate 1000 TARGET -oG ports_only.txt
PORTS=$(grep -oP '\d+/open' ports_only.txt | cut -d/ -f1 | tr '\n' ',' | sed 's/,$//')
nmap -sV -sC -p $PORTS TARGET -oN nmap_targeted.txt
```

### 3. Service Detection
```bash
nmap -sV --version-intensity 5 -p PORT1,PORT2 TARGET
nc -nv TARGET PORT <<< "" 2>&1 | head -5    # Banner grab
echo "" | nc -w 3 TARGET PORT
```

### 4. Script Scanning
```bash
nmap --script=vuln -p PORT TARGET
nmap --script=http-enum -p 80,443 TARGET
nmap --script=smb-enum-shares,smb-enum-users -p 445 TARGET
nmap --script=ftp-anon -p 21 TARGET
nmap --script=ssh-auth-methods -p 22 TARGET
```

### 5. UDP Scan
```bash
nmap -sU --top-ports 50 -T4 TARGET -oN nmap_udp.txt
nmap -sU -p 53,67,68,69,123,161,162,500,514,1900 TARGET
```

### 6. Firewall Evasion (when standard scans blocked)
```bash
nmap -f -sV -p PORT TARGET                    # Fragment packets
nmap -D RND:5 -sV -p PORT TARGET              # Decoy scan
nmap -sV -T2 -p PORT TARGET                   # Slow scan
nmap --source-port 53 -sV -p PORT TARGET      # Source port trick
```

### 7. Output Parsing
```bash
grep -oP '\d+/open/tcp//\S+' nmap_initial.gnmap
grep "open" nmap_initial.txt | grep -v "filtered"
```

## Common Port Reference

| Port | Service | Notes |
|------|---------|-------|
| 21 | FTP | Anonymous login |
| 22 | SSH | Version, auth methods |
| 25 | SMTP | Open relay, user enum |
| 53 | DNS | Zone transfer |
| 80/443 | HTTP/S | Web app testing |
| 139/445 | SMB | Shares, null sessions |
| 1433 | MSSQL | 3306 MySQL | 5432 PostgreSQL |
| 3389 | RDP | 5900 VNC | 6379 Redis (often unauth) |
| 8080 | HTTP alt | 27017 MongoDB (often unauth) |
