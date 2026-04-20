FROM projectdiscovery/katana:latest AS katana-bin

FROM kalilinux/kali-rolling:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV REDTEAM_SKIP_PREREQ_CHECKS=1
ENV REDTEAM_SKIP_DOCKER_IMAGE_CHECKS=1

RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' > /etc/apt/apt.conf.d/99redteam-retries && \
    rm -f /etc/apt/sources.list.d/kali.sources && \
    printf 'deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware\n' > /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    curl jq sqlite3 git ca-certificates \
    whois dnsutils ripgrep openssl wget netcat-openbsd procps lsof \
    python3 python3-venv python3-pip python3-dev \
    chromium chromium-driver \
    musl \
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

COPY agent/docker/redteam-allinone/entrypoint.sh /usr/local/bin/redteam-entrypoint
RUN chmod +x /usr/local/bin/redteam-entrypoint

WORKDIR /workspace
ENV REDTEAM_RUNTIME_MODE=local
ENV KATANA_LOCAL_BIN=/usr/local/bin/katana
ENV KATANA_CHROME_BIN=/usr/bin/chromium
ENV KATANA_HEADLESS_OPTIONS=--no-sandbox,--disable-dev-shm-usage,--disable-gpu
ENTRYPOINT ["/usr/local/bin/redteam-entrypoint"]
CMD ["opencode"]
