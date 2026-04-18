FROM kalilinux/kali-rolling:latest

RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' > /etc/apt/apt.conf.d/99redteam-retries && \
    rm -f /etc/apt/sources.list.d/kali.sources && \
    printf 'deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware\n' > /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    nikto \
    whatweb \
    dnsutils \
    whois \
    ffuf \
    gobuster \
    wfuzz \
    dirb \
    sqlmap \
    hydra \
    john \
    hashcat \
    nuclei \
    subfinder \
    curl \
    wget \
    jq \
    ripgrep \
    python3 \
    python3-pip \
    netcat-openbsd \
    openssl \
    wordlists \
    seclists \
    && apt-get clean \
    && find /var/lib/apt/lists -type f -delete

RUN ln -sf /usr/share/wordlists /wordlists && \
    ln -sf /usr/share/seclists /seclists

WORKDIR /engagement
ENTRYPOINT []
CMD ["bash"]
