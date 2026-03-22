<p align="center">
  <h1 align="center">🔴 RedTeam Agent</h1>
  <p align="center">
    <strong>Autonomous AI-Powered Red Team Simulation Agent</strong>
  </p>
  <p align="center">
    <a href="#installation">Install</a> · <a href="#quick-start">Quick Start</a> · <a href="#architecture">Architecture</a> · <a href="#中文说明">中文</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/CLI-Claude%20Code%20|%20OpenCode%20|%20Codex-blue" alt="CLI">
    <img src="https://img.shields.io/badge/platform-macOS%20|%20Linux-blue" alt="Platform">
    <img src="https://img.shields.io/badge/tools-Docker%20containerized-blue" alt="Docker">
    <img src="https://img.shields.io/badge/agents-8%20specialized-orange" alt="Agents">
    <img src="https://img.shields.io/badge/skills-31%20attack%20methodologies-red" alt="Skills">
    <img src="https://img.shields.io/badge/references-57%20files-green" alt="References">
  </p>
</p>

---

An autonomous red team simulation agent that works with **Claude Code**, **OpenCode**, and **Codex**. It transforms any workspace into a full penetration testing environment for CTF/lab targets — featuring **8 AI agents**, **containerized Kali tools**, a **streaming case collection pipeline**, and **57 security reference files**.

**Key Features:**
- **Multi-CLI support** — works with Claude Code, OpenCode, and Codex out of the box
- **Autonomous workflow** — 5-phase methodology (Recon → Collect → Test → Exploit+OSINT → Report) runs with minimal user interaction
- **Intelligence collection** — `intel.md` accumulates tech stack, people, domains, credentials from recon through exploitation; OSINT agent enriches with CVE, breach, DNS history, and social data
- **8 specialized agents** — operator, recon-specialist, source-analyzer, vulnerability-analyst, exploit-developer, fuzzer, osint-analyst, report-writer
- **Containerized tools** — all pentest tools run in Docker (Kali toolbox, mitmproxy, Katana), zero local installation
- **Case collection pipeline** — SQLite-backed queue with 4 producers, automatic type classification, zero-token dispatcher
- **57 reference files** — OWASP Top 10:2025, API Security 2023, offensive tactics, AD/Kerberos attacks
- **Resume support** — interrupt and continue any engagement without losing progress

## Installation

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Docker Compose)
- At least one AI CLI tool:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (recommended)
  - [OpenCode](https://opencode.ai) (`npm install -g opencode-ai`)
  - [Codex](https://github.com/openai/codex)
- Local tools: `curl`, `jq`, `sqlite3`
- Native Windows/PowerShell is not supported

### One-Line Install

**macOS / Linux:**
```bash
# Choose your CLI — each installs ONLY that product's files
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) opencode
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) claude
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) codex
```

This auto-clones the repo, installs product-specific files to `~/redteam-agent`, builds Docker images (if not already built), and runs verification.

### Manual Setup

**macOS / Linux:**
```bash
git clone https://github.com/NeoTheCapt/RedteamAgent.git
cd RedteamAgent

./install.sh opencode                  # Install for OpenCode
./install.sh claude                    # Install for Claude Code
./install.sh codex                     # Install for Codex
./install.sh opencode ~/my-project     # Custom directory
./install.sh --dry-run opencode        # Validate without writing
```

Windows is intentionally unsupported. Use a macOS/Linux environment for installation and runtime.

### Docker Images

| Image | Size | Contents |
|-------|------|----------|
| `kali-redteam` | ~3.5GB | nmap, ffuf, sqlmap, nikto, whatweb, hydra, gobuster, nuclei, wfuzz, wordlists, seclists |
| `redteam-proxy` | ~250MB | mitmproxy + case collection addon |
| `projectdiscovery/katana` | ~780MB | Web crawler + headless Chrome |

## Quick Start

```bash
cd ~/redteam-agent

# Choose your CLI:
claude              # Claude Code (recommended)
opencode            # OpenCode
codex               # Codex

# Semi-autonomous (asks for auth setup, confirms phases)
/engage http://your-ctf-target:8080

# Fully autonomous (zero interaction — just watch)
/autoengage http://your-ctf-target:8080

# Wildcard domain (enumerates subdomains, parallel testing)
/autoengage *.target.com --parallel 5
```

> **OpenCode users**: configure your LLM provider in `.opencode/opencode.json`:
> ```json
> { "model": "anthropic/claude-sonnet-4-6", "small_model": "anthropic/claude-haiku-4-5-20251001" }
> ```

### `/engage` vs `/autoengage`

| | `/engage` | `/autoengage` |
|---|---|---|
| Auth setup | Asks you to choose (proxy/cookie/skip) | Auto-skip, auto-register if endpoint found, auto-use discovered creds |
| Phase approval | Auto-confirm by default, first phase needs approval | Never asks. Every phase auto-proceeds. |
| Decisions | Parallel by default, can choose sequential | Always parallel. No options. |
| Errors | May stop on unexpected issues | Logs error, continues next task |
| When to use | First time on a target, want oversight | Repeat runs, overnight scans, maximum coverage |

The agent runs through 5 phases:

```
Phase 1: RECON ─── recon-specialist + source-analyzer (parallel)
    │
Phase 2: COLLECT ─ Import endpoints → SQLite queue, start Katana crawler
    │
Phase 3: TEST ──── Consume queue → vulnerability-analyst + source-analyzer
    │               exploit-developer runs in parallel for HIGH/MEDIUM findings
    │               (continuous loop with progress display)
Phase 4: EXPLOIT ── osint-analyst + exploit-developer (parallel)
    │               osint-analyst: CVE/breach/DNS/social intel from intel.md
    │               exploit-developer: chain analysis, impact assessment
    │               OSINT high-value intel → 2nd round exploitation
Phase 5: REPORT ── report-writer with coverage statistics + intelligence summary
```

### Commands

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

```
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
└── agent/                      ← ALL runtime files (what gets installed)
    ├── CLAUDE.md               ← operator prompt (Claude Code)
    ├── AGENTS.md               ← operator prompt (Codex)
    ├── .opencode/              ← OpenCode config + single source of truth
    │   ├── opencode.json       ← agent metadata, skills, commands, plugins
    │   ├── prompts/agents/     ← 8 agent prompts (.txt) — SINGLE SOURCE
    │   ├── commands/           ← 19 slash commands (.md) — SINGLE SOURCE
    │   └── plugins/            ← engagement hooks (TypeScript)
    ├── .claude/                ← Claude Code config (agents + commands generated)
    │   └── settings.json       ← hooks (scope check + auto-logging)
    ├── .codex/                 ← Codex config (agents generated)
    ├── scripts/
    │   ├── build-agents.sh     ← generates .claude/agents + .codex/agents + .claude/commands
    │   ├── dispatcher.sh       ← case queue management
    │   └── ...                 ← ingest, hooks, shared libraries
    ├── skills/                 ← 31 attack methodology skills
    ├── references/             ← 57 reference files (OWASP, tools, tactics, AD)
    ├── docker/                 ← Dockerfiles + docker-compose.yml
    └── engagements/            ← per-engagement output (created at runtime)
```

## CLI Compatibility

| Feature | Claude Code | OpenCode | Codex |
|---------|-------------|----------|-------|
| Operator prompt | `CLAUDE.md` | `.opencode/prompts/agents/operator.txt` | `AGENTS.md` |
| Subagents (8) | Generated `.claude/agents/*.md` | `.opencode/prompts/agents/*.txt` **(source)** | Generated `.codex/agents/*.toml` |
| Slash commands (19) | Generated `.claude/commands/*.md` | `.opencode/commands/*.md` **(source)** | Not supported — use natural language instead |
| Skills (31) | `skills/*/SKILL.md` (read on demand) | Loaded via instructions array | `skills/*/SKILL.md` (read on demand) |
| Build | `scripts/build-agents.sh` generates agents + commands | N/A (source files) | `scripts/build-agents.sh` generates agents |
| Auto-logging | `.claude/settings.json` hooks | `.opencode/plugins/engagement-hooks.ts` | N/A |
| Scope enforcement | Hook blocks out-of-scope | Hook warns out-of-scope | N/A |
| Agent attribution | `agent_type` in hook JSON | `chat.message` event tracking | N/A |

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

## Development

This repo has two layers:

- **Root** (`RedteamOpencode/`): dev workspace with install script and README. Run your CLI here for development tasks.
- **Agent** (`agent/`): all runtime files that get installed to `~/redteam-agent`. Run your CLI inside `agent/` (or `~/redteam-agent/`) for engagements.

### Single-Source Architecture

Agent prompts and commands are maintained **only** in OpenCode format (`.opencode/`). Claude Code and Codex versions are **generated at install time** by `install.sh`:

```bash
# install.sh handles building for the target product:
./install.sh claude ~/my-project   # generates .claude/agents/*.md + commands from .opencode/ sources
./install.sh codex ~/my-project    # generates .codex/agents/*.toml from .opencode/ sources
./install.sh opencode ~/my-project # copies .opencode/ directly (no build needed)
```

**To modify an agent:** edit `agent/.opencode/prompts/agents/<name>.txt`, then re-run `install.sh` for your product.

**To add a new agent:** create the `.txt` file, add agent entry to `opencode.json`, re-run `install.sh`.

**Operator prompts** (`CLAUDE.md`, `AGENTS.md`, `operator.txt`) are maintained separately — they contain platform-specific content that can't be single-sourced.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker images fail to build | `docker system prune -af && cd agent/docker && docker compose build --no-cache` |
| Katana doesn't start | Check: `docker logs redteam-katana` |
| Agent refuses to test target | Adjust auth in `agent/CLAUDE.md` or `agent/.opencode/instructions/INSTRUCTIONS.md` |
| Queue shows 0 cases | Run `/status` — check Collect phase was executed |
| ProviderModelNotFoundError | Set `model` in `agent/.opencode/opencode.json` |

## License

For authorized security testing only. Only use against targets you have explicit permission to test.

---

# 中文说明

## 简介

RedTeam Agent 是一个自主红队模拟 Agent，支持 **Claude Code**、**OpenCode** 和 **Codex** 三种 CLI 工具。它将任意工作空间转化为完整的渗透测试环境，专为 CTF/靶场目标设计。

**核心特性：**
- **多 CLI 支持** — 开箱即用支持 Claude Code、OpenCode、Codex
- **自主工作流** — 5 阶段方法论（侦察 → 收集 → 测试 → 利用+OSINT → 报告），最少用户干预
- **8 个专业 Agent** — 操作员、侦察专家、源码分析师、漏洞分析师、利用开发者、模糊测试器、OSINT 分析师、报告撰写者
- **情报收集** — `intel.md` 从侦察阶段开始积累技术栈、人员、域名、凭证等情报；OSINT 分析师通过联网数据源（CVE、泄露数据库、DNS 历史、社工情报）富化分析
- **容器化工具** — 所有渗透工具运行在 Docker 中（Kali 工具箱、mitmproxy、Katana），无需本地安装
- **用例收集管道** — 基于 SQLite 的队列，4 个生产者，15 种内容分类，零 token 消耗的调度器
- **57 个参考文件** — OWASP Top 10:2025、API 安全 2023、攻击战术、AD/Kerberos 攻击
- **断点续扫** — 中断后可从断点继续，不重复已完成的工作

## 快速开始

**macOS / Linux:**
```bash
# 一键安装（选择你的 CLI 工具）
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) opencode
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) claude
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh) codex
```

不支持原生 Windows / PowerShell。请使用 macOS 或 Linux 环境。

```bash
# 启动
cd ~/redteam-agent && opencode   # 或 claude / codex

# 半自主模式（需确认认证方式和首阶段）
/engage http://your-ctf-target:8080

# 全自动模式（零交互，自动注册、自动利用凭据、自动推进）
/autoengage http://your-ctf-target:8080

# 通配符域名（枚举子域名，并行渗透）
/autoengage *.target.com --parallel 5
```

## 工作流程

```
/engage → 侦察(并行) → 收集用例 → 消费测试+早期利用(循环) → 全量利用+OSINT情报(并行) → 报告

进度显示：
Phases: [x] Recon  [x] Collect  [>] Consume & Test  [ ] Exploit  [ ] Report
[queue] 120/495 done (24%) | api: 15/21 | page: 98/464 | findings: 5
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `/engage <url>` | 开始新的渗透测试（半自主） |
| `/autoengage <url>` | **全自动模式** — 零交互，最大覆盖 |
| `/resume` | 从中断处继续 |
| `/status` | 显示进度仪表盘 |
| `/proxy start/stop` | 管理代理（浏览器抓包） |
| `/auth cookie/header` | 配置认证信息 |
| `/queue` | 查看用例队列状态 |
| `/report` | 生成渗透测试报告 |
| `/stop` | 停止所有后台容器 |
| `/confirm auto/manual` | 切换自动/手动确认模式 |
| `/config [key] [value]` | 查看或设置运行时配置 |
| `/osint` | 对当前目标执行 OSINT 情报收集 |
| `/subdomain <domain>` | 枚举子域名 |

## 依赖

- Docker（含 Docker Compose）
- AI CLI 工具（至少一个）：Claude Code、OpenCode 或 Codex
- 本地工具：`curl`、`jq`、`sqlite3`
- 不支持原生 Windows / PowerShell

## 许可

仅用于授权的安全测试。请勿用于未经授权的目标。
