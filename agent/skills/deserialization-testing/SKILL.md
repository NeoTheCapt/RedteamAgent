---
name: deserialization-testing
description: Insecure deserialization detection and gadget chain exploitation
origin: RedteamOpencode
---

# Insecure Deserialization Testing

## When to Activate

- Binary or encoded blobs in cookies, parameters, or hidden fields
- Known serialization signatures in traffic
- Application uses Java (RMI, JMX), PHP, Python (pickle), or .NET

## Tools

- ysoserial (Java gadget chains)
- phpggc (PHP gadget chains)
- Burp Suite (Java Deserialization Scanner extension)
- ppickle exploit generator (Python)
- Custom scripts for .NET formatters

## Methodology

### 1. Identify Serialized Data

- [ ] Java: magic bytes `ac ed 00 05` (hex) or `rO0AB` (base64)
- [ ] PHP: `O:4:"User":2:{s:4:"name";...}` or `a:2:{...}`
- [ ] Python pickle: `\x80\x04\x95` header or `cos\nsystem\n` patterns
- [ ] .NET: `AAEAAAD/////` (base64 BinaryFormatter), XML with `<a1:` namespace
- [ ] Check cookies, ViewState, session storage, message queues, API params
- [ ] Check `Content-Type`: `application/x-java-serialized-object`, `application/x-php-serialized`

### 2. Java Deserialization

- [ ] Generate payloads with ysoserial:
      `java -jar ysoserial.jar CommonsCollections1 "id" | base64`
- [ ] Test common gadget chains: CommonsCollections1-7, Spring, Groovy, Hibernate
- [ ] Identify libraries in classpath from error messages or probing
- [ ] Test via cookies, POST body, RMI endpoints, JMX, T3 (WebLogic)
- [ ] Blind: DNS/HTTP callback payload to confirm execution

### 3. PHP Deserialization

- [ ] Modify serialized object: change property values
- [ ] Type juggling: change types in serialized data
- [ ] Generate payloads with phpggc:
      `phpggc Laravel/RCE1 system id`
- [ ] Target `__wakeup()`, `__destruct()`, `__toString()` magic methods
- [ ] Phar deserialization: upload `.phar` file, trigger via `phar://` wrapper

### 4. Python Pickle

- [ ] Craft malicious pickle:
      ```python
      import pickle, os
      class Exploit:
          def __reduce__(self):
              return (os.system, ('id',))
      pickle.dumps(Exploit())
      ```
- [ ] Test in cookies, session data, API payloads, cached objects
- [ ] Blind: use DNS/HTTP callback as command

### 5. .NET Deserialization

- [ ] Identify formatter: BinaryFormatter, DataContractSerializer, Json.NET
- [ ] ViewState deserialization (if MAC validation disabled)
- [ ] Generate payloads with ysoserial.net:
      `ysoserial.exe -g WindowsIdentity -f BinaryFormatter -c "cmd /c id"`
- [ ] Test TypeNameHandling in Json.NET: `"$type":` property injection

### 6. Impact Validation

- [ ] Confirm code execution with `id`, `whoami`, or DNS callback
- [ ] Read sensitive files
- [ ] Establish reverse shell if in scope
- [ ] Check if deserialized data affects application logic (role, permissions)

### 7. Data Tampering (Non-RCE)

- [ ] Modify user role/privilege in serialized session
- [ ] Change object references to access other users' data
- [ ] Alter numeric values (price, quantity, balance)

## What to Record

- Endpoint and parameter carrying serialized data
- Serialization format and language
- Gadget chain used (if RCE)
- Proof of execution (command output or callback)
- Libraries enabling the chain
- Severity: Critical (RCE) or High (data tampering)
- Remediation: avoid native deserialization, use allowlists, sign serialized data
