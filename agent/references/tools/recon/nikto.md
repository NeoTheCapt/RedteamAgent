# nikto

**Purpose:** Web server vulnerability scanner
For live engagement targets, run Nikto through the container boundary with `run_tool nikto`.

**Basic scan:** `run_tool nikto -h https://target`
**Specific port:** `run_tool nikto -h target -p 8080`
**With SSL:** `run_tool nikto -h https://target -ssl`
**Tuning (specific tests):** `run_tool nikto -h target -Tuning 123bde`
**Output:** `-o report.html -Format html`
