<p align="center">
  <h1 align="center">🔴 RedTeam Agent</h1>
  <p align="center">
    <strong>Autonomous AI-Powered Red Team Simulation Agent</strong>
  </p>
  <p align="center">
    <a href="#installation">Install</a> · <a href="#quick-start">Quick Start</a> · <a href="#architecture">Architecture</a> · <a href="#中文说明">中文</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/platform-macOS%20|%20Linux-blue" alt="Platform">
    <img src="https://img.shields.io/badge/tools-Docker%20containerized-blue" alt="Docker">
    <img src="https://img.shields.io/badge/agents-7%20specialized-orange" alt="Agents">
    <img src="https://img.shields.io/badge/skills-28%20attack%20methodologies-red" alt="Skills">
    <img src="https://img.shields.io/badge/references-57%20files-green" alt="References">
  </p>
</p>

---

An autonomous red team simulation agent built on [OpenCode](https://opencode.ai). It transforms any workspace into a full penetration testing environment for CTF/lab targets — featuring **7 AI agents**, **containerized Kali tools**, a **streaming case collection pipeline**, and **57 security reference files**.

**Key Features:**
- **Autonomous workflow** — 5-phase methodology (Recon → Collect → Test → Exploit → Report) runs with minimal user interaction
- **7 specialized agents** — operator, recon-specialist, source-analyzer, vulnerability-analyst, exploit-developer, fuzzer, report-writer
- **Containerized tools** — all pentest tools run in Docker (Kali toolbox, mitmproxy, Katana), zero local installation
- **Case collection pipeline** — SQLite-backed queue with 4 producers, automatic type classification, zero-token dispatcher
- **57 reference files** — OWASP Top 10:2025, API Security 2023, offensive tactics, AD/Kerberos attacks
- **Resume support** — interrupt and continue any engagement without losing progress

## Installation

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (with Docker Compose)
- [OpenCode](https://opencode.ai) CLI (`npm install -g opencode-ai`)
- Local tools: `curl`, `jq`, `sqlite3` (pre-installed on macOS/Linux)

### One-Line Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh)
```

This auto-clones the repo to `~/redteam-agent`, builds Docker images, and runs verification.

### Manual Setup

```bash
git clone https://github.com/NeoTheCapt/RedteamAgent.git ~/redteam-agent
cd ~/redteam-agent
./install.sh
```

After installation, configure your LLM provider in `.opencode/opencode.json`:
```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5"
}
```

Any OpenCode-compatible provider works: Anthropic, OpenAI, Google, Ollama (local).

### Docker Images

| Image | Size | Contents |
|-------|------|----------|
| `kali-redteam` | ~3.5GB | nmap, ffuf, sqlmap, nikto, whatweb, hydra, gobuster, nuclei, wfuzz, wordlists, seclists |
| `redteam-proxy` | ~250MB | mitmproxy + case collection addon |
| `projectdiscovery/katana` | ~780MB | Web crawler + headless Chrome |

## Quick Start

```bash
cd ~/redteam-agent
opencode

# Start an engagement
/engage http://your-ctf-target:8080
```

The agent automatically runs through 5 phases:

```
Phase 1: RECON ─── recon-specialist + source-analyzer (parallel)
    │
Phase 2: COLLECT ─ Import endpoints → SQLite queue, start Katana crawler
    │
Phase 3: TEST ──── Consume queue → vulnerability-analyst + source-analyzer
    │                               (continuous loop with progress display)
Phase 4: EXPLOIT ── exploit-developer (parallel per finding)
    │
Phase 5: REPORT ── report-writer with coverage statistics
```

### Commands

| Command | Description |
|---------|-------------|
| `/engage <url>` | Start a new engagement |
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
| `/recon` `/scan` `/enumerate` `/exploit` `/pivot` | Manual phase overrides |

### Authentication

```
1 — Proxy login (recommended): /proxy start → login in browser
2 — Manual cookie: /auth cookie "session=abc123"
3 — Manual header: /auth header "Authorization: Bearer ..."
4 — Skip: test unauthenticated surface, configure auth later
```

## Architecture

### 7 Agents

```
                    ┌─────────────────────────┐
                    │        OPERATOR          │
                    │  (primary — drives all)  │
                    └───┬──┬──┬──┬──┬──┬──────┘
                        │  │  │  │  │  │
  ┌─────────────────────┘  │  │  │  │  └───────────────────┐
  ▼                        ▼  │  ▼  │                      ▼
recon-         source-     │ vuln-  │              report-
specialist     analyzer    │ analyst│              writer
(network)      (code)      │ (test) │              (report)
                           ▼        ▼
                        fuzzer   exploit-
                        (fuzz)   developer
                                 (exploit)
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
.opencode/           OpenCode config (agents, commands, skills, plugins)
docker/              3 Dockerfiles + docker-compose.yml
scripts/             Dispatcher, ingest scripts, shared libraries
skills/              28 attack methodology skills
references/          57 reference files (OWASP, tools, tactics, AD)
engagements/         Per-engagement output (scope, logs, findings, queue, report)
```

## Customization

### Add a Skill

```bash
mkdir skills/my-skill
# Write skills/my-skill/SKILL.md with frontmatter + methodology
# Add "skills/my-skill/SKILL.md" to instructions array in opencode.json
```

### Add References

Add files to `references/<category>/` and update `references/INDEX.md`.

### Change LLM Provider

Edit `model` in `.opencode/opencode.json`. Supports Anthropic, OpenAI, Google, Ollama.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker images fail to build | `docker system prune -af && cd docker && docker compose build --no-cache` |
| Katana doesn't start | Check: `docker logs redteam-katana` |
| Agent refuses to test target | Adjust prompt in `.opencode/instructions/INSTRUCTIONS.md` |
| Queue shows 0 cases | Run `/status` — check Collect phase was executed |
| ProviderModelNotFoundError | Set `model` in `.opencode/opencode.json` |

## License

For authorized security testing only. Only use against targets you have explicit permission to test.

---

# 中文说明

## 简介

RedTeam Agent 是一个基于 [OpenCode](https://opencode.ai) 的自主红队模拟 Agent。它将任意工作空间转化为完整的渗透测试环境，专为 CTF/靶场目标设计。

**核心特性：**
- **自主工作流** — 5 阶段方法论（侦察 → 收集 → 测试 → 利用 → 报告），最少用户干预
- **7 个专业 Agent** — 操作员、侦察专家、源码分析师、漏洞分析师、利用开发者、模糊测试器、报告撰写者
- **容器化工具** — 所有渗透工具运行在 Docker 中（Kali 工具箱、mitmproxy、Katana），无需本地安装
- **用例收集管道** — 基于 SQLite 的队列，4 个生产者，15 种内容分类，零 token 消耗的调度器
- **57 个参考文件** — OWASP Top 10:2025、API 安全 2023、攻击战术、AD/Kerberos 攻击
- **断点续扫** — 中断后可从断点继续，不重复已完成的工作

## 快速开始

```bash
# 一键安装
bash <(curl -fsSL https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.sh)

# 配置 LLM（编辑 .opencode/opencode.json 设置 model 字段）

# 启动
cd ~/redteam-agent && opencode

# 开始渗透
/engage http://your-ctf-target:8080
```

## 工作流程

```
/engage → 侦察(并行) → 收集用例 → 消费测试(循环) → 漏洞利用(并行) → 生成报告

进度显示：
Phases: [x] Recon  [x] Collect  [>] Consume & Test  [ ] Exploit  [ ] Report
[queue] 120/495 done (24%) | api: 15/21 | page: 98/464 | findings: 5
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `/engage <url>` | 开始新的渗透测试 |
| `/resume` | 从中断处继续 |
| `/status` | 显示进度仪表盘 |
| `/proxy start/stop` | 管理代理（浏览器抓包） |
| `/auth cookie/header` | 配置认证信息 |
| `/queue` | 查看用例队列状态 |
| `/report` | 生成渗透测试报告 |
| `/stop` | 停止所有后台容器 |
| `/confirm auto/manual` | 切换自动/手动确认模式 |
| `/config [key] [value]` | 查看或设置运行时配置 |
| `/subdomain <domain>` | 枚举子域名 |

## 依赖

- Docker（含 Docker Compose）
- OpenCode CLI（`npm install -g opencode-ai`）
- 本地工具：`curl`、`jq`、`sqlite3`（macOS/Linux 预装）

## 许可

仅用于授权的安全测试。请勿用于未经授权的目标。
