# wfuzz

**Purpose:** Web fuzzing with advanced filtering
For live engagement targets, run wfuzz through the container boundary with `run_tool wfuzz`.

**Basic:** `run_tool wfuzz -c -w wordlist.txt https://target/FUZZ`
**POST parameter:** `run_tool wfuzz -c -w wordlist.txt -d "user=FUZZ&pass=test" https://target/login`
**Header fuzzing:** `run_tool wfuzz -c -w wordlist.txt -H "X-Custom: FUZZ" https://target/`
**Hide by status:** `--hc 404,403`
**Hide by word count:** `--hw 12`
**Hide by char count:** `--hh 1234`
**Multiple payloads:** `run_tool wfuzz -c -w users.txt -w passes.txt -d "user=FUZ2Z&pass=FUZZ" https://target/login`
