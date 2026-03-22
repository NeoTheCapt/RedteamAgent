# ffuf

**Purpose:** Web fuzzing (directories, parameters, vhosts)
For live engagement targets, use `run_tool ffuf` so fuzzing stays inside the engagement
container boundary.

**Directory fuzzing:** `run_tool ffuf -u https://target/FUZZ -w /path/to/wordlist.txt`
**Extension fuzzing:** `run_tool ffuf -u https://target/FUZZ -w wordlist.txt -e .php,.html,.txt`
**Parameter fuzzing:** `run_tool ffuf -u https://target/page?FUZZ=value -w params.txt`
**Vhost fuzzing:** `run_tool ffuf -u https://target -H "Host: FUZZ.target" -w subdomains.txt`
**Filter by status:** `-fc 404,403`
**Filter by size:** `-fs 1234`
**Output:** `-o results.json -of json`
