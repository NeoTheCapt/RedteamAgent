# ffuf

**Purpose:** Web fuzzing (directories, parameters, vhosts)

**Directory fuzzing:** `ffuf -u https://target/FUZZ -w /path/to/wordlist.txt`
**Extension fuzzing:** `ffuf -u https://target/FUZZ -w wordlist.txt -e .php,.html,.txt`
**Parameter fuzzing:** `ffuf -u https://target/page?FUZZ=value -w params.txt`
**Vhost fuzzing:** `ffuf -u https://target -H "Host: FUZZ.target" -w subdomains.txt`
**Filter by status:** `-fc 404,403`
**Filter by size:** `-fs 1234`
**Output:** `-o results.json -of json`
