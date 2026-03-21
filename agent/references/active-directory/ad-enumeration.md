# Active Directory Enumeration

## BloodHound
```bash
# Install
apt-get install bloodhound
neo4j console   # configure at http://localhost:7474 (neo4j:neo4j)
# Collect data
SharpHound.exe -c All
# Or PowerShell ingestor
Invoke-BloodHound -CollectionMethod All
```
- Upload .zip to BloodHound GUI; query shortest paths to DA

## PowerView Key Commands
```powershell
# Import
Import-Module PowerView.ps1
# Domain info
Get-NetDomain
Get-NetForest
Get-NetDomainController
# Users and groups
Get-NetUser | select samaccountname,description
Get-NetGroupMember "Domain Admins"
Get-NetLoggedon -ComputerName TARGET
# Trusts
Get-NetDomainTrust
Get-NetForestTrust
# ACLs
Get-ObjectAcl -SamAccountName "Domain Admins" -ResolveGUIDs
# Shares
Find-DomainShare -CheckShareAccess
# SPNs (for Kerberoasting)
Get-NetUser -SPN | select serviceprincipalname
```

## AD Module Without RSAT
```powershell
# Import DLL directly (no admin required)
Import-Module Microsoft.ActiveDirectory.Management.dll
Get-ADUser -Filter * -Properties *
Get-ADComputer -Filter * -Properties *
Get-ADGroup -Filter * -Properties *
```

## ACL/ACE Abuse
- Key rights to look for: GenericAll, GenericWrite, WriteOwner, WriteDACL, ForceChangePassword
```powershell
# Find users with GenericAll on target
Get-ObjectAcl -SamAccountName TARGET -ResolveGUIDs | ? {$_.ActiveDirectoryRights -eq "GenericAll"}
# GenericAll on user = reset password
# GenericAll on group = add yourself to group
# WriteDACL = grant yourself any rights
```
