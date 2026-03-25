FROM debian:bookworm-slim AS katana-bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

ARG KATANA_VERSION=1.5.0
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
      amd64) KATANA_ARCH="amd64" ;; \
      arm64) KATANA_ARCH="arm64" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL -o /tmp/katana.zip \
      "https://github.com/projectdiscovery/katana/releases/download/v${KATANA_VERSION}/katana_${KATANA_VERSION}_linux_${KATANA_ARCH}.zip" && \
    unzip -q /tmp/katana.zip -d /tmp/katana && \
    install -m 0755 /tmp/katana/katana /usr/local/bin/katana

FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV REDTEAM_SKIP_PREREQ_CHECKS=1
ENV REDTEAM_SKIP_DOCKER_IMAGE_CHECKS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    curl jq sqlite3 git ca-certificates \
    whois dnsutils ripgrep openssl wget netcat-openbsd procps lsof \
    python3 python3-venv python3-pip python3-dev \
    chromium chromium-driver \
    unzip \
    nmap nikto whatweb ffuf gobuster wfuzz dirb sqlmap hydra john hashcat nuclei subfinder \
    wordlists seclists \
    ruby-full metasploit-framework \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/mitmproxy-venv && \
    /opt/mitmproxy-venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/mitmproxy-venv/bin/pip install --no-cache-dir mitmproxy && \
    ln -sf /opt/mitmproxy-venv/bin/mitmdump /usr/local/bin/mitmdump && \
    ln -sf /opt/mitmproxy-venv/bin/mitmproxy /usr/local/bin/mitmproxy
RUN npm install -g opencode-ai@latest

COPY --from=katana-bin /usr/local/bin/katana /usr/local/bin/katana

COPY . /src
WORKDIR /src

RUN ./install.sh opencode /opt/redteam-agent

RUN ln -sf /usr/share/wordlists /wordlists && \
    ln -sf /usr/share/seclists /seclists

COPY docker/redteam-allinone/entrypoint.sh /usr/local/bin/redteam-entrypoint
RUN chmod +x /usr/local/bin/redteam-entrypoint

WORKDIR /workspace
ENV REDTEAM_RUNTIME_MODE=local
ENV KATANA_LOCAL_BIN=/usr/local/bin/katana
ENV KATANA_CHROME_BIN=/usr/bin/chromium
ENV KATANA_HEADLESS_OPTIONS=--no-sandbox,--disable-dev-shm-usage,--disable-gpu
ENTRYPOINT ["/usr/local/bin/redteam-entrypoint"]
CMD ["opencode"]
