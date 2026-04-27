<p align="center">
  <h1 align="center">🔴 RedTeam Agent</h1>
  <p align="center">
    <strong>Autonomous AI-Powered Red Team Simulation Agent</strong>
  </p>
  <p align="center">
    <a href="#installation">Install</a> · <a href="#quick-start">Quick Start</a> · <a href="#architecture">Architecture</a> · <a href="README.zh.md">中文</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/CLI-Claude%20Code%20|%20OpenCode%20|%20Codex-blue" alt="CLI">
    <img src="https://img.shields.io/badge/platform-macOS%20|%20Linux-blue" alt="Platform">
    <img src="https://img.shields.io/badge/tools-Docker%20containerized-blue" alt="Docker">
    <img src="https://img.shields.io/badge/agents-8%20specialized-orange" alt="Agents">
    <img src="https://img.shields.io/badge/skills-31%20attack%20methodologies-red" alt="Skills">
    <img src="https://img.shields.io/badge/references-79%20files-green" alt="References">
  </p>
</p>

---

An autonomous red team simulation agent that works with **Claude Code**, **OpenCode**, and **Codex**. It transforms any workspace into a full penetration testing environment for CTF/lab targets — featuring **8 AI agents**, **containerized Kali tools**, a **streaming case collection pipeline**, and **79 security reference files**.

## Demo

![RedTeam Agent demo (fast)](docs/redteam-agent-demo-fast.gif)

![RedTeam Agent GUI screenshot](docs/screenshot-20260331-181406.png)

**Key Features:**
- **Multi-CLI support** — works with Claude Code, OpenCode, and Codex out of the box
- **Autonomous workflow** — 5-phase methodology (Recon → Collect → Test → Exploit+OSINT → Report) runs with minimal user interaction; the Test phase is a streaming, stage-based case pipeline with serialized dispatch (one fetch + one subagent task per turn)
- **Orchestrator GUI** — local web UI for projects, live runs, artifacts, timelines, and terminal run metadata
- **Intelligence collection** — `intel.md` accumulates tech stack, people, domains, credentials from recon through exploitation; OSINT agent enriches with CVE, breach, DNS history, and social data
- **8 specialized agents** — operator, recon-specialist, source-analyzer, vulnerability-analyst, exploit-developer, fuzzer, osint-analyst, report-writer
- **Containerized tools** — all pentest tools run in Docker (Kali toolbox, mitmproxy, Katana, optional Metasploit RPC for OpenCode), zero local installation
- **Case collection pipeline** — SQLite-backed queue with 4 producers, automatic type classification, zero-token dispatcher, atomic fetch-dispatch pairing
- **79 reference files** — OWASP Top 10:2025, API Security 2023, offensive tactics, AD/Kerberos attacks
- **Resume support** — interrupt and continue any engagement without losing progress
- **Unattended hardening** — auto-resume after stalls, queue stall recovery, finding deduplication, surface coverage enforcement, and automatic report synthesis when report artifacts are missing or incomplete

## Installation

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Docker Compose)
- At least one AI CLI tool if you are not using the Docker all-in-one runtime:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  - [OpenCode](https://opencode.ai) (`npm install -g opencode-ai`)
  - [Codex](https://github.com/openai/codex)
- Local tools: `curl`, `jq`, `sqlite3` (not required for the Docker all-in-one runtime)
- Native Windows/PowerShell is not supported

### Installation Help

```bash
./install.sh -h
```

## Usage by CLI

### Docker (Recommended)

**Install**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) docker
# or:
./install.sh docker ~/redteam-docker
./install.sh --force docker ~/redteam-docker
```

**Start**

```bash
cd ~/redteam-docker
./run.sh
```

**Run**

```bash
/engage http://your-ctf-target:8080
/autoengage http://your-ctf-target:8080
```

**Notes**
- This is the cleanest runtime path: the image bundles OpenCode, Redteam Agent, and the pentest toolchain.
- `run.sh` starts from the image-baked clean template, persists engagement files in `workspace/`, and persists the OpenCode XDG dirs across restarts: `opencode-home/` (auth tokens), `opencode-config/` (model selection), `opencode-state/` (TUI state).
- Use `./run.sh --ephemeral-opencode` if you do not want to persist any OpenCode state outside the container (you'll have to reconfigure the model each run).
- Use `./run.sh --rebuild` to force a clean image rebuild after install.

### OpenCode (Recommended)

**Install**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) opencode
# or:
./install.sh opencode
./install.sh opencode ~/my-project
./install.sh --dry-run opencode
```

**Start**

```bash
cd ~/redteam-agent
opencode
```

**Run**

```bash
/engage http://your-ctf-target:8080
/autoengage http://your-ctf-target:8080
```

**Notes**
- Configure your LLM provider in `.opencode/opencode.json`.
- OpenCode can optionally use the local Metasploit MCP path during `Exploit` when a finding clearly maps to a known module family, service, product/version, or CVE.

### Claude Code

**Install**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) claude
# or:
./install.sh claude
./install.sh claude ~/my-project
```

**Start**

```bash
cd ~/redteam-agent
claude
```

**Run**

```bash
/engage http://your-ctf-target:8080
/autoengage http://your-ctf-target:8080
```

### Codex

**Install**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) codex
# or:
./install.sh codex
./install.sh codex ~/my-project
```

**Start**

```bash
cd ~/redteam-agent
codex
```

**Run**

```text
engage http://your-ctf-target:8080
autoengage http://your-ctf-target:8080
```

**Notes**
- Codex does not support slash commands the same way OpenCode and Claude Code do; use natural-language command invocation when needed.

### Local Orchestrator GUI (Optional)

Use the local web UI when you want to manage multiple workspaces or inspect live runs outside the CLI.

**Start**

```bash
./orchestrator/run.sh
# or rebuild the all-in-one image first:
./orchestrator/run.sh --rebuild
```

**Stop**

```bash
./orchestrator/stop.sh
```

**Notes**
- Default URL: `http://127.0.0.1:18000`
- `./orchestrator/run.sh` bootstraps the backend virtualenv, installs frontend dependencies if needed, and builds the frontend before starting.
- The UI exposes projects, live run status, task/phase timelines, artifacts, and terminal run metadata from the runs API.
- The backend auto-recovers incomplete runs after supervisor loss or backend restarts, synthesizes missing reports from engagement artifacts, and enforces completion health checks — making the UI suitable for long-running unattended sessions.

## Shared Outputs

Every runtime writes engagement artifacts to:

```text
engagements/<timestamp-target>/
```

Common outputs:
- `findings.md` — vulnerability findings and supporting evidence
- `report.md` — final engagement report
- `log.md` — execution log and operator timeline
- `intel.md` — summary intelligence safe for routine review
- `intel-secrets.json` — full captured secrets and tokens
- `auth.json` — active auth material and session state
- `cases.db` — SQLite queue, classification, and work state
- `surfaces.jsonl` — high-risk surface coverage tracking

Sensitive outputs:
- Do not casually share `intel-secrets.json`, `auth.json`, or any engagement directory that still contains live credentials, tokens, or session state.
- If you need to share results, prefer `report.md`, selected excerpts from `findings.md`, and a reviewed/redacted subset of supporting files.

## Engagement Modes

| | `/engage` | `/autoengage` |
|---|---|---|
| Auth setup | Asks you to choose (proxy/cookie/skip) | Auto-skip, auto-register if endpoint found, auto-use discovered creds |
| Phase approval | Auto-confirm by default, first phase needs approval | Never asks. Every phase auto-proceeds. |
| Decisions | Parallel by default, can choose sequential | Always parallel. No options. |
| Errors | May stop on unexpected issues | Logs error, continues next task |
| When to use | First time on a target, want oversight | Repeat runs, overnight scans, maximum coverage |

The agent runs through 5 phases:

```text
Phase 1: RECON ─── recon-specialist + source-analyzer (parallel)
    │
Phase 2: COLLECT ─ Import endpoints → SQLite queue, start Katana crawler
    │
Phase 3: TEST ──── Stage-based case pipeline (replaces strict phase gates):
    │               cases carry a `stage` column independent of `status`.
    │               Routing by stage+type:
    │                 ingested + {api,form,graphql,upload,websocket} → vuln-analyst
    │                 ingested + {javascript,page,stylesheet,data,unknown,api-spec} → source-analyzer
    │                 vuln_confirmed                                 → exploit-developer
    │                 fuzz_pending                                   → fuzzer (deep wordlists, >500 entries)
    │               Consume-test dispatch is SERIALIZED: one fetch + one task() per turn.
Phase 4: EXPLOIT ── osint-analyst + exploit-developer (parallel)
    │               osint-analyst: CVE/breach/DNS/social intel from intel.md
    │               exploit-developer: chain analysis, impact assessment
    │               osint-respawn: operator runs `intel_changed_check.sh` per
    │               loop tick; flag triggers a fresh osint correlation pass.
Phase 5: REPORT ── report-writer with coverage statistics + intelligence summary
```

## Common Commands

| Command | Description |
|---------|-------------|
| `/engage <url>` | Start a new engagement (semi-autonomous) |
| `/autoengage <url>` | **Fully autonomous** — zero interaction, max coverage |
| `/resume` | Continue an interrupted engagement |
| `/status` | Show progress dashboard with queue stats |
| `/proxy start/stop` | Manage mitmproxy interception proxy |
| `/auth cookie/header` | Configure authentication credentials |
| `/queue` | Show case queue statistics |
| `/report` | Generate final report |
| `/stop` | Stop all background containers |
| `/confirm auto/manual` | Toggle auto/manual approval mode |
| `/config [key] [value]` | View or set runtime configuration |
| `/subdomain <domain>` | Enumerate subdomains for a domain |
| `/vuln-analyze` | Analyze scan results for vulnerabilities |
| `/osint` | Run OSINT intelligence gathering on current engagement |
| `/recon` `/scan` `/enumerate` `/exploit` `/pivot` | Manual phase overrides |

### Authentication

```text
1 — Proxy login (recommended): /proxy start → login in browser
2 — Manual cookie: /auth cookie "session=abc123"
3 — Manual header: /auth header "Authorization: Bearer ..."
4 — Skip: test unauthenticated surface, configure auth later
```

## Architecture

### 8 Agents

```
                    ┌─────────────────────────┐
                    │        OPERATOR          │
                    │  (primary — drives all)  │
                    └──┬──┬──┬──┬──┬──┬──┬────┘
                       │  │  │  │  │  │  │
  ┌────────────────────┘  │  │  │  │  │  └──────────────────┐
  ▼                       ▼  │  ▼  │  │                     ▼
recon-         source-    │ vuln-  │  │             report-
specialist     analyzer   │ analyst│  │             writer
(network)      (code)     │ (test) │  │             (report)
  │              │        ▼        ▼  ▼
  │              │     fuzzer  exploit-  osint-
  │              │     (fuzz)  developer analyst
  │              │             (exploit) (OSINT)
  │              │                ▲        │
  │   intel.md ◄─┘                │        │
  └──► intel.md                   └────────┘
                              operator feeds
                            OSINT intel → exploit
```

### Case Pipeline

```
Producers              Queue (SQLite)         Consumers
┌──────────┐
│ mitmproxy │─┐   ┌──────────┐  ┌────────┐  ┌─ vuln-analyst (api/form)
│ Katana    │─┼──→│ cases.db │─→│dispatch│──┼─ source-analyzer (js/css)
│ recon     │─┤   └──────────┘  │ (.sh)  │  ├─ fuzzer (deep params)
│ spec      │─┘   dedup+state   └────────┘  └─ exploit-dev (confirmed)
└──────────┘      15 types       0 tokens      ▲
     ▲                                         │
     └──────────── new endpoints ──────────────┘
```

### Directory Structure

```
RedteamOpencode/                ← dev workspace (git root)
├── install.sh                  ← installs agent/ to ~/redteam-agent
├── README.md                   ← project docs
│
├── agent/                      ← ALL agent runtime files (what gets installed)
│   ├── CLAUDE.md               ← operator prompt (Claude Code)
│   ├── AGENTS.md               ← operator prompt (Codex)
│   ├── .opencode/              ← OpenCode config + single source of truth
│   │   ├── opencode.json       ← agent metadata, skills, commands, plugins
│   │   ├── prompts/agents/     ← 8 agent prompts (.txt) — SINGLE SOURCE
│   │   ├── commands/           ← 19 slash commands (.md) — SINGLE SOURCE
│   │   └── plugins/            ← engagement hooks (TypeScript)
│   ├── .claude/                ← Claude Code config (agents + commands generated)
│   │   └── settings.json       ← hooks (scope check + auto-logging)
│   ├── .codex/                 ← Codex config (agents generated)
│   ├── scripts/
│   │   ├── install-time generators ← install.sh builds .claude/agents + .codex/agents + .claude/commands
│   │   ├── dispatcher.sh       ← case queue management
│   │   └── ...                 ← ingest, hooks, shared libraries
│   ├── skills/                 ← 31 attack methodology skills
│   ├── references/             ← 79 reference files (OWASP, tools, tactics, AD)
│   ├── docker/                 ← Dockerfiles + docker-compose.yml
│   └── engagements/            ← per-engagement output (created at runtime)
│
└── orchestrator/               ← optional web UI (FastAPI backend + React frontend)
    ├── backend/                ← Python API; reads from agent/ via agent_source_dir
    └── frontend/               ← React shell (Documents / Events / Progress / Cases tabs)
```

## CLI Compatibility

| Feature | Claude Code | OpenCode | Codex |
|---------|-------------|----------|-------|
| Operator prompt | `CLAUDE.md` | `.opencode/prompts/agents/operator.txt` | `AGENTS.md` |
| Subagents (8) | Generated `.claude/agents/*.md` | `.opencode/prompts/agents/*.txt` **(source)** | Generated `.codex/agents/*.toml` |
| Slash commands (19) | Generated `.claude/commands/*.md` | `.opencode/commands/*.md` **(source)** | Not supported — use natural language instead |
| Skills (31) | `skills/*/SKILL.md` (read on demand) | Loaded via instructions array | `skills/*/SKILL.md` (read on demand) |
| Build | `install.sh claude` generates agents + commands at install time | N/A (source files) | `install.sh codex` generates agents at install time |
| Auto-logging | `.claude/settings.json` hooks | `.opencode/plugins/engagement-hooks.ts` | N/A |
| Scope enforcement | Hook blocks out-of-scope | Hook warns out-of-scope | N/A |
| Agent attribution | `agent_type` in hook JSON | `chat.message` event tracking | N/A |

**Development-only wrappers**
- `agent/.claude/agents/operator.md` and `agent/.codex/agents/operator.toml` exist only for working inside the source repo.
- Installed Claude/Codex workspaces keep `CLAUDE.md` or `AGENTS.md` as the operator entrypoint and install only generated subagents.

## Customization

### Add a Skill

```bash
mkdir agent/skills/my-skill
# Write agent/skills/my-skill/SKILL.md with frontmatter + methodology
# Add "skills/my-skill/SKILL.md" to instructions array in agent/.opencode/opencode.json
```

### Add References

Add files to `agent/references/<category>/` and update `agent/references/INDEX.md`.

### Change LLM Provider (OpenCode)

Edit `model` in `agent/.opencode/opencode.json`. Supports Anthropic, OpenAI, Google, Ollama.

### Per-Project Configuration

Each project stores its own config, inherited by every run launched under it. Configure via the **Edit project** button in the Sidebar or NewRunForm, which opens the Project Edit modal with 6 tabs:

| Tab | Fields | Env vars injected into run container |
|-----|--------|--------------------------------------|
| **Model** | provider_id, model_id, small_model_id, api_key, base_url | `REDTEAM_OPENCODE_MODEL`, `REDTEAM_OPENCODE_SMALL_MODEL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` (or `ANTHROPIC_*`) |
| **Auth** | JSON blob for cookies / headers / tokens | Written to `auth.json` in seed dir |
| **Env** | Free-form JSON `{"VAR": "value"}` | Merged into container env |
| **Crawler** | Katana crawl parameters | `KATANA_CRAWL_DEPTH`, `KATANA_CRAWL_DURATION`, `KATANA_TIMEOUT_SECONDS`, `KATANA_CONCURRENCY`, `KATANA_PARALLELISM`, `KATANA_RATE_LIMIT`, `KATANA_STRATEGY`, `KATANA_ENABLE_HYBRID`, `KATANA_ENABLE_XHR`, `KATANA_ENABLE_HEADLESS`, `KATANA_ENABLE_JSLUICE`, `KATANA_ENABLE_PATH_CLIMB` |
| **Parallel** | Concurrency ceiling | `REDTEAM_MAX_PARALLEL_BATCHES` |
| **Agents** | Enable/disable per subagent | `REDTEAM_DISABLED_AGENTS` (comma-separated list of disabled agent IDs when any are off) |

**Defaults**: Empty JSON `{}` for every config category. When a key is absent, the runtime falls back to the value baked into `.env` or the agent defaults. Fields only override when explicitly set.

**Precedence**: `crawler_json` / `parallel_json` / `agents_json` win over free-form `env_json`. To clear a field, set it to `""` (empty string), not `null`.

## Development

### Directory Convention (READ BEFORE CONTRIBUTING)

This repo has a **strict three-layer split** — do not cross the lines:

| Layer | Purpose | Examples |
|-------|---------|----------|
| **Repo root** | Meta only — install script, docs, CI | `install.sh`, `README*.md`, `.gitignore`, `docs/` |
| **`agent/`** | ALL agent runtime (**canonical**) | `.opencode/`, `scripts/`, `skills/`, `references/`, `docker/`, prompts, operator core |
| **`orchestrator/`** | Optional web UI (reads `agent/`, never copies from root) | `backend/` (FastAPI), `frontend/` (React) |

**Rule**: `agent/` is the single source of truth for the agent runtime. The orchestrator backend hardcodes `agent_source_dir = REPO_ROOT / "agent"` (`orchestrator/backend/app/config.py:17`) and syncs from there into each engagement's workspace. `install.sh` also installs from `agent/` into the target dir.

**DO NOT** create root-level `/.opencode/`, `/scripts/`, `/skills/`, `/references/`, or `/docker/`. Edit the `agent/`-scoped copy instead.

Two guards are in place:

1. **`.gitignore`** blocks those paths at `git add` time.
2. **Pre-commit hook** at `agent/scripts/hooks/block-root-dup-dirs.sh` refuses the commit if the paths slip through. Install once per clone:

   ```bash
   cp agent/scripts/hooks/block-root-dup-dirs.sh .git/hooks/pre-commit
   chmod +x .git/hooks/pre-commit
   ```

### Where to run your CLI

- **Root** (`RedteamOpencode/`): dev workspace. Run CLI here for repo-level tooling (tests, docs work, orchestrator dev).
- **`agent/`**: runtime home. Run CLI inside `agent/` (or the installed target `~/redteam-agent/`) to drive engagements.

### Single-Source Architecture

Agent prompts and commands are maintained **only** in OpenCode format (`.opencode/`). Claude Code and Codex versions are **generated at install time** by `install.sh`:

```bash
# install.sh handles building for the target product:
./install.sh claude ~/my-project   # generates .claude/agents/*.md + commands at install time
./install.sh codex ~/my-project    # generates .codex/agents/*.toml at install time
./install.sh opencode ~/my-project # copies .opencode/ directly (no build needed)
```

**To modify an agent:** edit `agent/.opencode/prompts/agents/<name>.txt`, then re-run `install.sh` for your product.

**To add a new agent:** create the `.txt` file, add agent entry to `opencode.json`, re-run `install.sh`.

**Operator prompts** use a mixed model:
- `agent/.opencode/prompts/agents/operator.txt` stays as the OpenCode source prompt
- `agent/operator-core.md` is the shared Claude/Codex methodology body
- `agent/scripts/render-operator-prompts.sh` renders `CLAUDE.md`, `AGENTS.md`, and the thin local operator wrappers
- `bash tests/agent-contracts/check-operator-prompts.sh` verifies the generated files are still in sync

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker images fail to build | `docker system prune -af && cd agent/docker && docker compose build --no-cache` |
| Docker build fails while fetching Kali packages | Re-run the build. The Dockerfiles configure apt retry/timeout and pin Kali to the official mirror, but transient network failures can still require another attempt. |
| Katana doesn't start | Check: `docker logs redteam-katana` |
| Agent refuses to test target | Adjust auth in `agent/CLAUDE.md` or `agent/.opencode/instructions/INSTRUCTIONS.md` |
| Queue shows 0 cases | Run `/status` — check Collect phase was executed |
| ProviderModelNotFoundError | Set `model` in `agent/.opencode/opencode.json` |

## License

For authorized security testing only. Only use against targets you have explicit permission to test.
