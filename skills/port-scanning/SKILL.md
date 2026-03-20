---
name: port-scanning
description: Discover open ports, running services, and their versions on a target
origin: RedteamOpencode
---

# Port Scanning

## When to Activate

- Initial reconnaissance of a new target host or network
- Need to discover running services before vulnerability testing
- Verifying firewall rules or filtered ports
- New IP address discovered during engagement

## Tools

- `nmap` — primary port scanner, service detection, scripting engine
- `nc` (netcat) — quick port checks, banner grabbing

## Methodology

### 1. Quick Initial Scan

Fast scan of common ports to get an early picture.

```bash
# Top 1000 ports with service detection and default scripts
nmap -sV -sC -T4 TARGET -oN nmap_initial.txt

# Output in all formats for later reference
nmap -sV -sC -T4 TARGET -oA nmap_initial
```

### 2. Full TCP Port Scan

Comprehensive scan of all 65535 TCP ports.

```bash
# Full port range, service detection
nmap -sV -sC -T4 -p- TARGET -oN nmap_full_tcp.txt

# If speed is critical, discover ports first then probe
nmap -sS -T4 -p- --min-rate 1000 TARGET -oG ports_only.txt
# Extract open ports
PORTS=$(grep -oP '\d+/open' ports_only.txt | cut -d/ -f1 | tr '\n' ',' | sed 's/,$//')
# Deep scan only open ports
nmap -sV -sC -p $PORTS TARGET -oN nmap_targeted.txt
```

### 3. Service Version Detection

```bash
# Aggressive version detection
nmap -sV --version-intensity 5 -p PORT1,PORT2 TARGET

# Banner grabbing with netcat
nc -nv TARGET PORT <<< "" 2>&1 | head -5

# Banner grab with timeout
echo "" | nc -w 3 TARGET PORT
```

### 4. Script Scanning

```bash
# Default scripts (safe)
nmap -sC -p PORT TARGET

# Specific script categories
nmap --script=vuln -p PORT TARGET
nmap --script=auth -p PORT TARGET
nmap --script=default,safe -p PORT TARGET

# Specific scripts for known services
nmap --script=http-enum -p 80,443 TARGET
nmap --script=smb-enum-shares,smb-enum-users -p 445 TARGET
nmap --script=ftp-anon -p 21 TARGET
nmap --script=ssh-auth-methods -p 22 TARGET
```

### 5. UDP Scan

UDP scanning is slower. Target the most common UDP services.

```bash
# Top 50 UDP ports
nmap -sU --top-ports 50 -T4 TARGET -oN nmap_udp.txt

# Specific UDP services to check
nmap -sU -p 53,67,68,69,123,161,162,500,514,1900 TARGET -oN nmap_udp_targeted.txt

# Combined TCP+UDP
nmap -sS -sU --top-ports 100 TARGET -oN nmap_combined.txt
```

### 6. Firewall/IDS Evasion (If Needed)

Use only when standard scans are being blocked.

```bash
# Fragment packets
nmap -f -sV -p PORT TARGET

# Decoy scan
nmap -D RND:5 -sV -p PORT TARGET

# Slow scan to avoid rate-based detection
nmap -sV -T2 -p PORT TARGET

# Specific source port (some firewalls allow 53, 80)
nmap --source-port 53 -sV -p PORT TARGET
```

### 7. Output Parsing

```bash
# Extract open ports from greppable output
grep -oP '\d+/open/tcp//\S+' nmap_initial.gnmap

# List all open ports one per line
grep "open" nmap_initial.txt | grep -v "filtered"

# Extract service versions
grep "open" nmap_full_tcp.txt | awk '{print $1, $3, $4, $5}'
```

## Common Port Reference

| Port | Service | Notes |
|------|---------|-------|
| 21 | FTP | Check anonymous login |
| 22 | SSH | Version, auth methods |
| 25 | SMTP | Open relay, user enum |
| 53 | DNS | Zone transfer |
| 80/443 | HTTP/S | Web app testing |
| 110/143 | POP3/IMAP | Mail services |
| 139/445 | SMB | Shares, null sessions |
| 389/636 | LDAP/S | Directory services |
| 1433 | MSSQL | Database |
| 3306 | MySQL | Database |
| 3389 | RDP | Remote desktop |
| 5432 | PostgreSQL | Database |
| 5900 | VNC | Remote access |
| 6379 | Redis | Often unauthenticated |
| 8080/8443 | HTTP alt | Web apps, admin panels |
| 27017 | MongoDB | Often unauthenticated |

## What to Record

- **Open ports:** port number, protocol (TCP/UDP), state
- **Services:** service name and exact version string
- **Script output:** any notable findings from NSE scripts
- **Banners:** raw banner text from services
- **Filtered ports:** ports that appear filtered (may indicate firewall)
- **OS hints:** if OS detection was run, record the guess
- **Anomalies:** unexpected ports, non-standard services, version mismatches
