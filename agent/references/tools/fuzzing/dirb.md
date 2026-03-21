# dirb

**Purpose:** Web directory brute-forcing

**Basic:** `dirb https://target`
**Custom wordlist:** `dirb https://target /path/to/wordlist.txt`
**With cookie:** `dirb https://target -c "session=abc123"`
**Custom agent:** `dirb https://target -a "Mozilla/5.0"`
**Ignore specific codes:** `dirb https://target -N 403`
**Output:** `-o results.txt`
