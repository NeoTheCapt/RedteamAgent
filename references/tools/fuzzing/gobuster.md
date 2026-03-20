# gobuster

**Purpose:** Directory and DNS brute-forcing

**Directory mode:** `gobuster dir -u https://target -w /path/to/wordlist.txt`
**With extensions:** `gobuster dir -u https://target -w wordlist.txt -x php,html,txt`
**DNS subdomain:** `gobuster dns -d target.com -w subdomains.txt`
**Vhost mode:** `gobuster vhost -u https://target -w wordlist.txt`
**Threads:** `-t 50`
**Output:** `-o results.txt`
