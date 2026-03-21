# wfuzz

**Purpose:** Web fuzzing with advanced filtering

**Basic:** `wfuzz -c -w wordlist.txt https://target/FUZZ`
**POST parameter:** `wfuzz -c -w wordlist.txt -d "user=FUZZ&pass=test" https://target/login`
**Header fuzzing:** `wfuzz -c -w wordlist.txt -H "X-Custom: FUZZ" https://target/`
**Hide by status:** `--hc 404,403`
**Hide by word count:** `--hw 12`
**Hide by char count:** `--hh 1234`
**Multiple payloads:** `wfuzz -c -w users.txt -w passes.txt -d "user=FUZ2Z&pass=FUZZ" https://target/login`
