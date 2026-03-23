FROM projectdiscovery/katana:latest AS katana-bin

FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV REDTEAM_SKIP_PREREQ_CHECKS=1
ENV REDTEAM_SKIP_DOCKER_IMAGE_CHECKS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    curl jq sqlite3 git ca-certificates \
    whois dnsutils ripgrep openssl wget netcat-openbsd procps lsof \
    python3 python3-venv python3-pip python3-dev \
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
ENTRYPOINT ["/usr/local/bin/redteam-entrypoint"]
CMD ["opencode"]
