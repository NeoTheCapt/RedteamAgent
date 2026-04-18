# whatweb

**Purpose:** Web technology fingerprinting
For live engagement targets, run WhatWeb inside the engagement container with `run_tool whatweb`.

**Basic:** `run_tool whatweb https://target`
**Aggressive:** `run_tool whatweb -a 3 https://target`
**Multiple targets:** `run_tool whatweb --input-file=$DIR/scans/targets.txt`
**Verbose:** `run_tool whatweb -v https://target`
**Output:** `--log-json=results.json`
