FROM node:22-slim

# System tools needed by redteam agent
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq sqlite3 git ca-certificates \
    whois dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Install opencode globally
RUN npm install -g opencode-ai@latest

# Docker CLI (for run_tool to work — talks to host Docker via socket mount)
RUN curl -fsSL https://get.docker.com | sh || true

# Working directory
WORKDIR /workspace

# The agent directory gets mounted at /workspace
ENTRYPOINT ["opencode"]
