# hashcat

**Purpose:** GPU-accelerated password hash cracking

**MD5:** `hashcat -m 0 hashes.txt wordlist.txt`
**SHA256:** `hashcat -m 1400 hashes.txt wordlist.txt`
**NTLM:** `hashcat -m 1000 hashes.txt wordlist.txt`
**bcrypt:** `hashcat -m 3200 hashes.txt wordlist.txt`
**With rules:** `hashcat -m 0 hashes.txt wordlist.txt -r rules/best64.rule`
**Show cracked:** `hashcat -m 0 hashes.txt --show`
**Brute-force:** `hashcat -m 0 -a 3 hashes.txt ?a?a?a?a?a?a`
**Status:** press `s` during run
