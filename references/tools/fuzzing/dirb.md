# dirb

**Purpose:** Web directory brute-forcing

For live engagement targets, prefer `run_tool ffuf` or `run_tool gobuster` first. If you
need `dirb`, run it through the container boundary with `run_tool dirb`.

**Basic:** `run_tool dirb https://target`
**Custom wordlist:** `run_tool dirb https://target /path/to/wordlist.txt`
**Explicit cookie override:** `run_tool dirb https://target -c "session=alternate-user"`
**Custom agent:** `run_tool dirb https://target -a "Mozilla/5.0"`
**Ignore specific codes:** `run_tool dirb https://target -N 403`
**Output:** `-o results.txt`
