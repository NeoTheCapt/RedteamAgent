# RDP Lateral Movement

## RDP Hijacking with tscon (T1076)
- Requires SYSTEM privileges; no password needed
```cmd
# Elevate to SYSTEM
psexec -s cmd
# List sessions
query user
# Hijack session (ID=2) to current console
tscon 2 /dest:console
```
- Reconnects to target user's desktop without password prompt
- Detection: tscon.exe run as SYSTEM, events 4778/4779

## Headless RDP with SharpRDP
```cmd
SharpRDP.exe computername=TARGET command=calc username=DOMAIN\admin password=pass
```
- Executes commands via RDP without GUI session
- Detection: mstscax.dll loaded by unusual binaries, connections to port 3389

## Cobalt Strike: Beacon to RDP
- Use socks proxy + rdesktop/xfreerdp through beacon tunnel
- Or use SharpRDP through execute-assembly

## Notes
- RDP creates detailed logon event trails (4624 type 10)
- NLA (Network Level Authentication) adds pre-auth barrier
- RDP hijacking bypasses NLA since session already authenticated
