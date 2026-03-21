# john (John the Ripper)

**Purpose:** Offline password hash cracking

**Auto-detect hash:** `john hashes.txt`
**With wordlist:** `john --wordlist=/path/to/wordlist.txt hashes.txt`
**Specific format:** `john --format=raw-md5 hashes.txt`
**Show cracked:** `john --show hashes.txt`
**Rules (mangling):** `john --wordlist=wordlist.txt --rules hashes.txt`
**List formats:** `john --list=formats`
