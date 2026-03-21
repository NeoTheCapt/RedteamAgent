FROM kalilinux/kali-rolling:latest

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
