# RedTeam Agent

An autonomous red team simulation agent powered by OpenCode. Transforms any workspace into a penetration testing environment for CTF/lab targets with 7 specialized AI agents, containerized tools, and a streaming case collection pipeline.

## Installation

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Docker Compose)
- [OpenCode](https://opencode.ai) CLI (`npm install -g opencode-ai`)
- Local tools: `curl`, `jq`, `sqlite3` (pre-installed on macOS/Linux)

### Quick Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh)
```

### Full Setup

```bash
# Clone the project
git clone https://github.com/NeoTheCapt/RedteamAgent.git ~/redteam-agent
cd ~/redteam-agent

# Run the installer (checks prerequisites, builds Docker images, runs smoke test)
./install.sh

# Configure your LLM provider
# Edit .opencode/opencode.json and set the "model" field:
#   "model": "anthropic/claude-sonnet-4-5"    # Anthropic
#   "model": "openai/gpt-4o"                  # OpenAI
#   "model": "google/gemini-2.5-pro"          # Google
```

The installer will:
1. Verify Docker, OpenCode, curl, jq, sqlite3 are available
2. Pull/build 3 Docker images (~4.5GB total)
3. Run a smoke test to verify container execution
4. Check OpenCode configuration

### Docker Images

All pentest tools run in containers. No local tool installation required.

| Image | Size | Contents | Run Mode |
|-------|------|----------|----------|
| `kali-redteam` | ~3.5GB | nmap, ffuf, sqlmap, nikto, whatweb, hydra, gobuster, nuclei, wfuzz, wordlists, seclists | One-shot (`docker run --rm`) |
| `redteam-proxy` | ~250MB | mitmproxy + proxy_addon.py | Persistent (`docker run -d`, port 8080) |
| `projectdiscovery/katana` | ~780MB | Katana web crawler + headless Chrome | Persistent (`docker run -d`) |

To rebuild images after changes: `cd docker && docker compose build`

## Usage

### Starting an Engagement

```bash
# Launch OpenCode in the project directory
opencode

# Start a new engagement against a CTF target
/engage http://your-ctf-target:8080
```

The agent will:
1. Create an engagement directory with scope, logs, and case queue
2. Check Docker images and local tools
3. Ask you to configure authentication (proxy login, manual cookie, or skip)
4. Run through 5 phases automatically, asking for approval at each transition

### Engagement Workflow

```
/engage http://target
    |
    v
Phase 1: RECON
    recon-specialist + source-analyzer (parallel)
    Network fingerprinting, directory fuzzing, JS/CSS analysis
    |
    v
Phase 2: COLLECT
    Import recon endpoints → cases.db
    Start Katana crawler (Docker container)
    Start proxy if configured (Docker container)
    |
    v
Phase 3: CONSUME & TEST (main loop)
    Fetch cases by type from queue → dispatch to agents:
      api/form/upload → vulnerability-analyst
      page/js/css     → source-analyzer
    Record findings, requeue new endpoints
    |
    v
Phase 4: EXPLOIT (parallel)
    Dispatch exploit-developer for each confirmed vulnerability
    Multiple exploits run in parallel on independent findings
    |
    v
Phase 5: REPORT
    report-writer generates findings report with coverage stats
```

### Commands

| Command | Description |
|---------|-------------|
| `/engage <url>` | Start a new engagement against a target |
| `/proxy start/stop` | Start or stop the mitmproxy interception proxy |
| `/auth cookie/header` | Configure authentication credentials |
| `/queue` | Show case queue statistics |
| `/status` | Show engagement progress and findings |
| `/report` | Generate final engagement report |
| `/stop` | Stop all background containers (proxy, katana) |
| `/recon` | Manual override: run reconnaissance |
| `/scan` | Manual override: run port scanning |
| `/enumerate` | Manual override: run deep enumeration |
| `/vuln-analyze` | Manual override: run vulnerability analysis |
| `/exploit` | Manual override: exploit a specific finding |
| `/pivot` | Force strategy change |
| `/resume` | Resume an interrupted engagement from where it left off |
| `/confirm auto/manual` | Toggle auto-confirm (default) or manual approval mode |

### Authentication

Three ways to configure authentication for testing protected endpoints:

1. **Proxy capture** (recommended): `/proxy start`, configure browser to use `http://127.0.0.1:8080`, login to target. The proxy auto-captures cookies and tokens.

2. **Manual cookie**: `/auth cookie "session=abc123; token=xyz"`

3. **Manual header**: `/auth header "Authorization: Bearer eyJhbG..."`

4. **Skip**: Test unauthenticated attack surface only. Configure auth later with `/auth`.

After configuring auth, the agent will re-crawl with credentials to discover authenticated endpoints.

### Case Collection Pipeline

The agent systematically collects and tests endpoints through a SQLite-backed queue:

**Producers** (feed endpoints into the queue):
- Katana web crawler (Docker container, runs continuously)
- mitmproxy browser proxy (Docker container, captures real browsing)
- Recon agent endpoint import
- OpenAPI/Swagger spec parser

**Consumers** (test endpoints from the queue):
- vulnerability-analyst: API, form, upload, GraphQL, WebSocket cases
- source-analyzer: HTML pages, JavaScript, CSS, data files
- fuzzer: deep parameter fuzzing (triggered by vulnerability-analyst)

**Key features:**
- Each case consumed exactly once (`pending → processing → done`)
- New endpoints discovered during testing flow back into the queue
- 15 content-type classifications with automatic routing
- Zero-token queue operations via `dispatcher.sh` (bash + sqlite3)

View queue status: `/queue`

## Architecture

### Agents

| Agent | Mode | Role |
|-------|------|------|
| `operator` | primary | Drives the engagement, coordinates phases, dispatches subagents |
| `recon-specialist` | subagent | Network reconnaissance: fingerprinting, fuzzing, scanning |
| `source-analyzer` | subagent | Frontend code analysis: JS/CSS/HTML for hidden routes and secrets |
| `vulnerability-analyst` | subagent | Vulnerability testing: SQLi, XSS, SSRF, auth bypass |
| `exploit-developer` | subagent | Exploit crafting and execution with evidence capture |
| `fuzzer` | subagent | High-volume parameter and directory fuzzing |
| `report-writer` | subagent | Engagement report generation with coverage statistics |

### Containerized Tools

All pentest tools execute inside Docker containers via `run_tool`:

```bash
source scripts/lib/container.sh
export ENGAGEMENT_DIR="engagements/2026-03-20-143500-target"
run_tool nmap -sV -sC target
run_tool ffuf -u http://target/FUZZ -w /wordlists/dirb/common.txt
run_tool sqlmap -u "http://target/api?id=1" --batch
```

The container mounts the engagement directory at `/engagement` and provides wordlists at `/wordlists` and `/seclists`.

### Directory Structure

```
.opencode/                    # OpenCode configuration
  opencode.json               # Agents, commands, skills, model config
  commands/                   # 13 slash command templates
  instructions/               # Global methodology and rules
  prompts/agents/             # 7 agent system prompts
  plugins/                    # Engagement logging plugin
docker/                       # Docker infrastructure
  kali-redteam/Dockerfile     # Main toolbox image
  mitmproxy/Dockerfile        # Proxy image
  katana/Dockerfile           # Crawler image
  docker-compose.yml          # Build orchestration
scripts/                      # Operational scripts
  dispatcher.sh               # Zero-token queue engine
  proxy_addon.py              # mitmproxy addon for case collection
  katana_ingest.sh            # Katana output → SQLite ingest
  recon_ingest.sh             # Agent endpoint → SQLite ingest
  spec_ingest.sh              # OpenAPI spec → SQLite ingest
  schema.sql                  # SQLite database schema
  lib/                        # Shared bash libraries
    container.sh              # Docker container abstraction
    params.sh                 # Parameter extraction
    classify.sh               # Content-type classification
    db.sh                     # Database helpers
skills/                       # 12 attack methodology skills
references/                   # 57 reference files (OWASP, tools, tactics)
  INDEX.md                    # Reference index (loaded as instructions)
  vuln-checklists/            # OWASP Top 10:2025
  api-security/               # OWASP API Top 10:2023
  tools/                      # CLI tool cheatsheets
  offensive-tactics/           # Red team TTPs
  active-directory/           # AD/Kerberos attacks
engagements/                  # Per-engagement output
  <date>-<time>-<target>/
    scope.json                # Target definition
    log.md                    # Chronological engagement log
    findings.md               # Confirmed vulnerabilities
    cases.db                  # SQLite case queue
    auth.json                 # Authentication credentials
    report.md                 # Final report
    downloads/                # Downloaded files (JS, HTML, CSS)
    scans/                    # Scan output (ffuf, nmap, katana)
    tools/                    # Custom scripts generated during engagement
    pids/                     # Background process tracking
```

## Customization

### Adding Skills

```bash
mkdir skills/my-skill
cat > skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: Description of when this skill should be used
origin: RedteamOpencode
---

# My Skill

## When to Activate
- conditions...

## Methodology
1. steps...
EOF
```

Add to `opencode.json`: `"instructions": [..., "skills/my-skill/SKILL.md"]`

### Adding References

Add files to the appropriate subdirectory under `references/` and update `references/INDEX.md`.

### Changing LLM Provider

Edit `.opencode/opencode.json`:
```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5"
}
```

Any OpenCode-compatible provider works (Anthropic, OpenAI, Google, local models via Ollama).

## Troubleshooting

### Docker images fail to build
```bash
# Clean Docker cache and rebuild
docker system prune -af
cd docker && docker compose build --no-cache
```

### Katana doesn't start
The container requires `--network host`. Check: `docker logs redteam-katana`

### Tools not found inside container
Verify the kali-redteam image has the tool: `docker run --rm kali-redteam which <tool>`

### Agent refuses to test target
All targets are treated as local CTF/lab environments. If the agent still hesitates, the LLM's safety filters may be interfering. Try a different model or adjust the prompt in `.opencode/instructions/INSTRUCTIONS.md`.

### Queue shows 0 cases
Check that Collect phase was executed. Run `/queue` to see stats. If empty, endpoints weren't imported — check `scans/katana_output.jsonl` and recon output.

## License

This project is for authorized security testing only. Only use against targets you have explicit permission to test.
