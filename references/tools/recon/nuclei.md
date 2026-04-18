# nuclei

**Purpose:** Vulnerability scanning with community templates
For live engagement targets, prefer `run_tool nuclei` so scans stay in the engagement
container boundary and reuse the mounted workspace.

**Basic scan:** `run_tool nuclei -u https://target`
**Specific template:** `run_tool nuclei -u https://target -t cves/2021/CVE-2021-44228.yaml`
**By severity:** `run_tool nuclei -u https://target -severity critical,high`
**By tag:** `run_tool nuclei -u https://target -tags cve,rce`
**Multiple targets:** `run_tool nuclei -l $DIR/scans/targets.txt`
**Update templates:** `run_tool nuclei -update-templates`
**Output:** `-o results.txt`, `-jsonl` (JSON lines)
**Rate limit:** `-rate-limit 100`
