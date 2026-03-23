# OpenCode Runner (Containerized)

Run OpenCode + RedTeam Agent in a clean Docker container, isolated from host system state.

## Quick Start

```bash
cd docker/opencode-runner

# Copy and fill in API keys
cp .env.example .env
vim .env

# Build and run
docker compose build
docker compose run --rm opencode
```

## What It Does

- Runs OpenCode in a fresh Linux container (no macOS-specific issues)
- Mounts `agent/` as the workspace (your prompts, skills, scripts)
- Mounts Docker socket so `run_tool` can spawn pentest tool containers
- Persists OpenCode state (sessions, db) across runs via named volumes
- Passes API keys from `.env` into the container

## Alternative: Single-Image Runtime

This repo is also gaining a separate all-in-one image under
`docker/redteam-allinone/`:
- OpenCode + Redteam Agent + toolchain in one image
- `REDTEAM_RUNTIME_MODE=local`
- no per-tool child containers for normal execution

Use `opencode-runner` if you want the current Docker-socket-based host workflow.
Use `redteam-allinone` if you want a more self-contained container runtime.

## Usage

```bash
# Interactive session
docker compose run --rm opencode

# Reset OpenCode state (fresh start, no session history)
docker compose down -v
docker compose run --rm opencode

# Build with no cache (get latest opencode)
docker compose build --no-cache
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY not set` | Fill in `.env` file |
| `docker.sock permission denied` | Run: `sudo chmod 666 /var/run/docker.sock` |
| `network_mode: host` not working on macOS | Docker Desktop limitation — targets must be reachable from container network. Use `host.docker.internal` instead of `127.0.0.1` |
