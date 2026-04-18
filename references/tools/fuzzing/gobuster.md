# gobuster

**Purpose:** Directory and DNS brute-forcing
For live engagement targets, run Gobuster through the container boundary with `run_tool gobuster`.

**Directory mode:** `run_tool gobuster dir -u https://target -w /path/to/wordlist.txt`
**With extensions:** `run_tool gobuster dir -u https://target -w wordlist.txt -x php,html,txt`
**DNS subdomain:** `run_tool gobuster dns -d target.com -w subdomains.txt`
**Vhost mode:** `run_tool gobuster vhost -u https://target -w wordlist.txt`
**Threads:** `-t 50`
**Output:** `-o results.txt`
