# OWASP Juice Shop 漏洞清单 — 扫描器准召分析用

> **版本**: Juice Shop v19.x (master branch, 111 challenges)
> **数据来源**: [challenges.yml](https://github.com/juice-shop/juice-shop/blob/master/data/static/challenges.yml) / [Pwning OWASP Juice Shop](https://pwning.owasp-juice.shop)
> **用途**: 对照扫描器输出，计算 Precision / Recall / F1

---

## 一、准召指标计算公式

| 指标 | 公式 | 含义 |
|------|------|------|
| **Precision（准确率）** | TP / (TP + FP) | 扫描器报出的漏洞中，有多少是真实的 |
| **Recall（召回率）** | TP / (TP + FN) | 已知漏洞中，扫描器发现了多少 |
| **F1 Score** | 2 × P × R / (P + R) | 准确率和召回率的调和平均 |

- **TP（True Positive）**: 扫描器正确检出的漏洞（在下表中标记 ✅）
- **FP（False Positive）**: 扫描器报出但实际不存在的漏洞（来自扫描器报告，不在此表中）
- **FN（False Negative）**: 实际存在但扫描器未检出的漏洞（在下表中标记 ❌）

---

## 二、漏洞分类汇总 (16 Categories)

| 分类 | 挑战数 | OWASP Top 10 映射 | CWE | 自动化扫描可覆盖度 |
|------|--------|-------------------|-----|-------------------|
| Broken Access Control | 12 | A1:2025 | CWE-22,285,639,918 | 中 |
| Broken Anti Automation | 4 | A6:2025 / OAT-009 | CWE-362 | 低 |
| Broken Authentication | 12 | A7:2025 | CWE-287,352,521,620,640 | 中 |
| Cryptographic Issues | 5 | A4:2025 | CWE-326,327,328,950 | 低 |
| Improper Input Validation | 11 | ASVS V5 / API6 | CWE-20,434 | 高 |
| Injection | 10 | A5:2025 | CWE-74,89,943,1336 | 高 |
| Insecure Deserialization | 2 | A8:2025 | CWE-502 | 低 |
| Miscellaneous | 8 | — | — | 低 |
| Observability Failures | 4 | A9:2025 | CWE-117,532 | 中 |
| Security Misconfiguration | 4 | A2:2025 | CWE-209 | 高 |
| Security through Obscurity | 3 | A6:2025 | CWE-656 | 低 |
| Sensitive Data Exposure | 14 | A4:2025 / API3 | CWE-200,530,548 | 中 |
| Unvalidated Redirects | 3 | A10:2013 | CWE-601 | 高 |
| Vulnerable Components | 5 | A3:2025 | CWE-506,829,1104 | 高（SCA） |
| XSS | 10 | A5:2025 | CWE-79 | 高 |
| XXE | 2 | A2:2025 | CWE-611,776 | 高 |
| **合计** | **111** | | | |

---

## 三、完整挑战清单 (111 Challenges)

> **使用说明**: 在「检出」列填写 ✅ 或 ❌，最后统计即可得出 TP 和 FN。

### 3.1 Injection (10)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Login Admin | ⭐⭐ | CWE-89 | SQL Injection | `POST /rest/user/login` (email field) | |
| 2 | Login Bender | ⭐⭐⭐ | CWE-89 | SQL Injection | `POST /rest/user/login` (email field) | |
| 3 | Login Jim | ⭐⭐⭐ | CWE-89 | SQL Injection | `POST /rest/user/login` (email field) | |
| 4 | Database Schema | ⭐⭐⭐ | CWE-89 | UNION SQL Injection | `GET /rest/products/search?q=` | |
| 5 | User Credentials | ⭐⭐⭐⭐ | CWE-89 | UNION SQL Injection | `GET /rest/products/search?q=` | |
| 6 | Christmas Special | ⭐⭐⭐⭐ | CWE-89 | Blind SQL Injection | `GET /rest/products/search?q=` | |
| 7 | Ephemeral Accountant | ⭐⭐⭐⭐ | CWE-89 | Stacked SQL Injection | `POST /rest/user/login` | |
| 8 | NoSQL Manipulation | ⭐⭐⭐⭐ | CWE-943 | NoSQL Injection (query operator) | `PATCH /rest/products/reviews` | |
| 9 | NoSQL DoS | ⭐⭐⭐⭐ | CWE-943 | NoSQL Injection (sleep) | `POST /rest/products/reviews` | |
| 10 | NoSQL Exfiltration | ⭐⭐⭐⭐⭐ | CWE-943 | NoSQL Injection ($where) | `GET /rest/track-order/{id}` | |
| 11 | SSTi | ⭐⭐⭐⭐⭐⭐ | CWE-1336 | Server-Side Template Injection | Profile page / username | |

### 3.2 XSS (10)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | DOM XSS | ⭐ | CWE-79 | DOM-based XSS | `/#/search?q=<payload>` | |
| 2 | Bonus Payload (DOM XSS) | ⭐ | CWE-79 | DOM XSS (bonus payload) | `/#/search?q=<bonus>` | |
| 3 | Reflected XSS | ⭐⭐ | CWE-79 | Reflected XSS | `/#/track-result?id=<payload>` | |
| 4 | Bonus Payload (Reflected) | ⭐⭐ | CWE-79 | Reflected XSS (bonus) | `/#/track-result?id=<bonus>` | |
| 5 | API-only XSS | ⭐⭐⭐ | CWE-79 | Stored XSS via REST API | `PUT /api/Products/{id}` | |
| 6 | Client-side XSS Protection | ⭐⭐⭐ | CWE-79 | Stored XSS (bypass client validation) | `POST /api/Users` (email) | |
| 7 | CSP Bypass | ⭐⭐⭐⭐ | CWE-79 | CSP Bypass + XSS | `/#/track-result` (legacy page) | |
| 8 | HTTP-Header XSS | ⭐⭐⭐⭐ | CWE-79 | Stored XSS via HTTP Header | True-Client-IP → Last Login IP | |
| 9 | Server-side XSS Protection | ⭐⭐⭐⭐ | CWE-79 | Recursive Sanitization Bypass | `POST /api/Feedbacks` (comment) | |
| 10 | Video XSS | ⭐⭐⭐⭐⭐⭐ | CWE-79 | XSS via Video Subtitle (VTT) | Promotion video subtitles | |

### 3.3 Broken Access Control (12)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Web3 Sandbox | ⭐ | CWE-285 | Forced Browsing | `/#/web3-sandbox` | |
| 2 | Admin Section | ⭐⭐ | CWE-285 | Forced Browsing | `/#/administration` | |
| 3 | Five-Star Feedback | ⭐⭐ | CWE-285 | Missing Function-Level Access Control | `DELETE /api/Feedbacks/{id}` | |
| 4 | View Basket | ⭐⭐ | CWE-639 | IDOR | `GET /rest/basket/{id}` | |
| 5 | Forged Feedback | ⭐⭐⭐ | CWE-639 | IDOR / Parameter Tampering | `POST /api/Feedbacks` | |
| 6 | Forged Review | ⭐⭐⭐ | CWE-639 | IDOR / Parameter Tampering | `PUT /rest/products/{id}/reviews` | |
| 7 | Manipulate Basket | ⭐⭐⭐ | CWE-639 | HTTP Parameter Pollution / IDOR | `POST /api/BasketItems` | |
| 8 | Product Tampering | ⭐⭐⭐ | CWE-285 | Missing API Access Control | `PUT /api/Products/{id}` | |
| 9 | Easter Egg | ⭐⭐⭐⭐ | CWE-548 | Path Traversal + Null Byte | `/ftp/eastere.gg` | |
| 10 | Privilege Escalation via BOLA | ⭐⭐⭐⭐⭐ | CWE-639 | BOLA / IDOR | Various API endpoints | |
| 11 | SSRF | ⭐⭐⭐⭐⭐⭐ | CWE-918 | Server-Side Request Forgery | Profile image URL field | |
| 12 | Local File Read | ⭐⭐⭐⭐⭐⭐ | CWE-22 | Local File Inclusion / SSRF | Profile image URL (`file://`) | |

### 3.4 Broken Authentication (12)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Password Strength | ⭐⭐ | CWE-521 | Weak Password (admin123) | `POST /rest/user/login` | |
| 2 | Determine John's Security Q | ⭐⭐ | CWE-640 | Security Question OSINT | `/#/forgot-password` | |
| 3 | Bjoern's Favorite Pet | ⭐⭐⭐ | CWE-640 | Security Question OSINT | `/#/forgot-password` | |
| 4 | GDPR Data Erasure | ⭐⭐⭐ | CWE-287 | Improper Data Erasure | `POST /rest/user/login` | |
| 5 | Reset Jim's Password | ⭐⭐⭐ | CWE-640 | Security Question OSINT | `/#/forgot-password` | |
| 6 | Login Bjoern (OAuth) | ⭐⭐⭐⭐ | CWE-287 | OAuth Implementation Flaw | OAuth login flow | |
| 7 | Reset Bender's Password | ⭐⭐⭐⭐ | CWE-640 | Security Question OSINT | `/#/forgot-password` | |
| 8 | Change Bender's Password | ⭐⭐⭐⭐⭐ | CWE-620 | Current Password Bypass | `GET /rest/user/change-password` | |
| 9 | Reset Bjoern's Password | ⭐⭐⭐⭐⭐ | CWE-640 | Security Question OSINT | `/#/forgot-password` | |
| 10 | Two Factor Authentication | ⭐⭐⭐⭐⭐ | CWE-287 | 2FA Bypass | `POST /rest/2fa/verify` | |
| 11 | Login CISO (OAuth) | ⭐⭐⭐⭐⭐ | CWE-287 | OAuth Exploit | OAuth login flow | |
| 12 | Login Support Team | ⭐⭐⭐⭐⭐⭐ | CWE-522 | Weak Credential Storage (3rd party) | `POST /rest/user/login` | |

### 3.5 Sensitive Data Exposure (14)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Confidential Document | ⭐ | CWE-548 | Directory Listing | `/ftp/acquisitions.md` | |
| 2 | NFT Takeover | ⭐⭐ | CWE-200 | Leaked Seed Phrase | Photo wall / reviews | |
| 3 | Login MC SafeSearch | ⭐⭐ | CWE-200 | Weak Password / OSINT | `POST /rest/user/login` | |
| 4 | Visual Geo Stalking | ⭐⭐ | CWE-200 | EXIF Data Leakage | `/#/photo-wall` → Exif | |
| 5 | Meta Geo Stalking | ⭐⭐ | CWE-200 | EXIF Data Leakage | `/#/photo-wall` → Exif | |
| 6 | Login Amy | ⭐⭐⭐ | CWE-200 | Weak Password / OSINT | `POST /rest/user/login` | |
| 7 | Forgotten Developer Backup | ⭐⭐⭐⭐ | CWE-530 | Null Byte Injection | `/ftp/package.json.bak%2500.md` | |
| 8 | Forgotten Sales Backup | ⭐⭐⭐⭐ | CWE-530 | Null Byte Injection | `/ftp/coupons_2013.md.bak%2500.pdf` | |
| 9 | GDPR Data Theft | ⭐⭐⭐⭐ | CWE-200 | IDOR in Data Export | `GET /rest/user/data-export` | |
| 10 | Leaked Unsafe Product | ⭐⭐⭐⭐ | CWE-200 | OSINT + SQL Injection | `/#/contact` | |
| 11 | Poison Null Byte | ⭐⭐⭐⭐ | CWE-158 | Null Byte Injection | `/ftp/encrypt.pyc%2500.md` | |
| 12 | Reset Uvogin's Password | ⭐⭐⭐⭐ | CWE-200 | Leaked Credentials | `/#/forgot-password` | |
| 13 | Email Leak | ⭐⭐⭐⭐⭐ | CWE-200 | JSONP Information Disclosure | `/rest/user/whoami?callback=` | |
| 14 | Leaked Access Logs | ⭐⭐⭐⭐⭐ | CWE-532 | Password Spraying | External paste → login | |

### 3.6 Improper Input Validation (11)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Missing Encoding | ⭐ | CWE-20 | URL Encoding Issue | `/#/photo-wall` (broken image) | |
| 2 | Repetitive Registration | ⭐ | CWE-20 | Missing Server-side Validation | `POST /api/Users` | |
| 3 | Zero Stars | ⭐ | CWE-20 | Missing Input Validation | `POST /api/Feedbacks` (rating:0) | |
| 4 | Empty User Registration | ⭐⭐ | CWE-20 | Missing Input Validation | `POST /api/Users` | |
| 5 | Admin Registration | ⭐⭐⭐ | CWE-20 | Mass Assignment | `POST /api/Users` (role field) | |
| 6 | Deluxe Fraud | ⭐⭐⭐ | CWE-20 | Business Logic Bypass | `POST /rest/deluxe-membership` | |
| 7 | Mint the Honey Pot | ⭐⭐⭐ | CWE-20 | NFT Minting Exploit | NFT endpoint | |
| 8 | Overwrite Zero Lives | ⭐⭐⭐ | CWE-20 | Client-side Manipulation | Score Board game | |
| 9 | Payback Time | ⭐⭐⭐ | CWE-20 | Negative Quantity | `PUT /api/BasketItems/{id}` | |
| 10 | Upload Size | ⭐⭐⭐ | CWE-434 | File Upload Size Bypass | `/#/complain` | |
| 11 | Upload Type | ⭐⭐⭐ | CWE-434 | File Upload Type Bypass | `/#/complain` | |
| 12 | Expired Coupon | ⭐⭐⭐⭐ | CWE-20 | Time-based Bypass | `PUT /rest/basket/{id}/coupon/{code}` | |

### 3.7 Security Misconfiguration (4)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Error Handling | ⭐ | CWE-209 | Information Exposure via Error | Various forms / invalid input | |
| 2 | Deprecated Interface | ⭐⭐ | CWE-16 | Deprecated API Endpoint | B2B XML upload interface | |
| 3 | Login Support Team | ⭐⭐⭐⭐⭐⭐ | CWE-522 | Weak Credential Storage | `POST /rest/user/login` | |
| 4 | Exposed Metrics | ⭐ | CWE-200 | Information Disclosure | `/metrics` (Prometheus) | |

### 3.8 Vulnerable Components (5)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Legacy Typosquatting | ⭐⭐⭐⭐ | CWE-506 | npm Typosquatting | `package.json.bak` analysis | |
| 2 | Frontend Typosquatting | ⭐⭐⭐⭐⭐ | CWE-506 | Frontend Typosquatting | `package.json` (frontend deps) | |
| 3 | Supply Chain Attack | ⭐⭐⭐⭐⭐ | CWE-506 | Supply Chain Analysis | `package.json` dependencies | |
| 4 | Unsigned JWT | ⭐⭐⭐⭐⭐ | CWE-347 | JWT None Algorithm Attack | Authorization header (`alg:none`) | |
| 5 | Forged Signed JWT | ⭐⭐⭐⭐⭐⭐ | CWE-347 | JWT Algorithm Confusion (RS→HS) | Authorization header | |
| 6 | Arbitrary File Write | ⭐⭐⭐⭐⭐⭐ | CWE-829 | Arbitrary File Write | File upload endpoints | |

### 3.9 Cryptographic Issues (5)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Weird Crypto | ⭐⭐ | CWE-328 | Weak Hashing (MD5) | `/#/contact` | |
| 2 | Nested Easter Egg | ⭐⭐⭐⭐ | CWE-326 | Base64 + ROT13 Decoding | `/ftp/eastere.gg` content | |
| 3 | 噜噜噜 | ⭐⭐⭐⭐⭐ | CWE-327 | Crypto Exploit | Various | |
| 4 | Forged Coupon | ⭐⭐⭐⭐⭐⭐ | CWE-327 | Weak Crypto / Reverse Engineering | Coupon code generation | |
| 5 | Imaginary Challenge | ⭐⭐⭐⭐⭐⭐ | CWE-328 | Crypto Reverse Engineering | Continue Code / backup | |
| 6 | Premium Paywall | ⭐⭐⭐⭐⭐⭐ | CWE-326 | Weak Key Management | Score Board | |

### 3.10 Insecure Deserialization (2)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Blocked RCE DoS | ⭐⭐⭐⭐⭐ | CWE-502 | Deserialization RCE | B2B interface (XML/JSON) | |
| 2 | Successful RCE DoS | ⭐⭐⭐⭐⭐⭐ | CWE-502 | Deserialization RCE | B2B interface | |

### 3.11 XXE (2)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | XXE Data Access | ⭐⭐⭐ | CWE-611 | XXE File Read (/etc/passwd) | B2B XML upload | |
| 2 | XXE DoS | ⭐⭐⭐⭐⭐ | CWE-776 | XML Bomb / Billion Laughs | B2B XML upload | |

### 3.12 Unvalidated Redirects (3)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Outdated Allowlist | ⭐ | CWE-601 | Open Redirect | `/redirect?to=https://blockchain.info/...` | |
| 2 | Whitelist Bypass | ⭐⭐⭐⭐ | CWE-601 | Open Redirect (allowlist bypass) | `/redirect?to=` | |
| 3 | Allowlist Bypass via Redirect | ⭐⭐⭐⭐ | CWE-601 | Open Redirect | `/redirect?to=` | |

### 3.13 Broken Anti Automation (4)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Reset Morty's Password | ⭐⭐ | CWE-307 | Brute Force (no rate limiting) | `/#/forgot-password` | |
| 2 | CAPTCHA Bypass | ⭐⭐⭐ | CWE-804 | CAPTCHA Bypass / Automation | `POST /api/Feedbacks` | |
| 3 | Extra Language | ⭐⭐⭐⭐⭐ | CWE-425 | Brute Force + Enumeration | `/i18n/{lang}.json` | |
| 4 | Multiple Likes | ⭐⭐⭐⭐⭐⭐ | CWE-362 | Race Condition | `POST /rest/products/{id}/reviews/{id}/likes` | |

### 3.14 Security through Obscurity (3)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Privacy Policy Inspection | ⭐⭐⭐ | CWE-656 | Hidden URL in Policy | Privacy policy page | |
| 2 | Steganography | ⭐⭐⭐⭐ | CWE-656 | Steganography Analysis | Product images | |
| 3 | Blockchain Hype | ⭐⭐⭐⭐⭐ | CWE-656 | Code Deobfuscation | `/#/tokensale` (obfuscated) | |

### 3.15 Observability Failures (4)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Exposed Metrics | ⭐ | CWE-200 | Information Disclosure | `/metrics` | |
| 2 | Access Log | ⭐⭐⭐⭐ | CWE-532 | Path Traversal / Info Disclosure | `/support/logs` | |
| 3 | Misplaced Signature File | ⭐⭐⭐⭐ | CWE-532 | Null Byte + Path Traversal | `/ftp/suspicious_errors.yml%2500.md` | |
| 4 | Leaked Access Logs | ⭐⭐⭐⭐⭐ | CWE-532 | Password Spraying | External paste site | |

### 3.16 Miscellaneous (8)

| # | Challenge | 难度 | CWE | 攻击向量 | 关键 Endpoint | 检出 |
|---|-----------|------|-----|----------|--------------|------|
| 1 | Score Board | ⭐ | — | Forced Browsing | `/#/score-board` | |
| 2 | Privacy Policy | ⭐ | — | Navigation | `/#/privacy-security/privacy-policy` | |
| 3 | Mass Dismiss | ⭐ | — | UI Feature Discovery | Score Board notifications | |
| 4 | Kill Chatbot | ⭐ | — | Prompt Injection | Support Chat | |
| 5 | Bully Chatbot | ⭐ | — | Social Engineering | Support Chat | |
| 6 | Security Policy | ⭐⭐ | — | security.txt | `/.well-known/security.txt` | |
| 7 | GDPR Compliance | ⭐⭐⭐ | — | Feature Usage | `/#/privacy-security/data-export` | |
| 8 | Retrieve Blueprint | ⭐⭐⭐⭐⭐ | CWE-200 | Forced Browsing | `/assets/public/images/products/3d_keychain.stl` | |
| 9 | Wallet Depletion | ⭐⭐⭐⭐⭐⭐ | CWE-841 | Smart Contract Reentrancy | Web3 wallet contract | |

---

## 四、关键扫描端点清单

以下是自动化扫描器应重点覆盖的 Endpoint：

| Endpoint | 漏洞类型 | Method | 可自动扫描 |
|----------|----------|--------|-----------|
| `POST /rest/user/login` | SQL Injection, Brute Force, Credential Stuffing | POST | ✅ |
| `GET /rest/products/search?q=` | SQL Injection (UNION, Blind) | GET | ✅ |
| `POST /api/Users` | Mass Assignment, XSS, Input Validation | POST | ✅ |
| `POST /api/Feedbacks` | XSS, IDOR, CAPTCHA Bypass | POST | ✅ |
| `PUT /api/Products/{id}` | Broken Access Control, XSS | PUT | ✅ |
| `GET /rest/basket/{id}` | IDOR | GET | ✅ |
| `POST /api/BasketItems` | HTTP Parameter Pollution, IDOR | POST | ✅ |
| `/ftp/` | Directory Listing, Path Traversal, Null Byte | GET | ✅ |
| `/#/administration` | Forced Browsing | GET | ⚠️ Client-side |
| `/#/search?q=` | DOM XSS | GET | ✅ |
| `/#/track-result?id=` | Reflected XSS, CSP Bypass | GET | ✅ |
| `/redirect?to=` | Open Redirect | GET | ✅ |
| `GET /rest/user/change-password` | CSRF, Auth Bypass | GET | ✅ |
| `/#/forgot-password` | Security Question Bypass, Brute Force | POST | ⚠️ 需交互 |
| `/api/Challenges` | Information Disclosure | GET | ✅ |
| `/metrics` | Prometheus Info Disclosure | GET | ✅ |
| `/.well-known/security.txt` | Security Policy Disclosure | GET | ✅ |
| `/rest/user/whoami?callback=` | JSONP Information Leak | GET | ✅ |
| `PATCH /rest/products/reviews` | NoSQL Injection, IDOR | PATCH | ✅ |
| `GET /rest/track-order/{id}` | NoSQL Injection ($where) | GET | ✅ |
| `POST /rest/2fa/verify` | 2FA Bypass | POST | ⚠️ 需逻辑 |
| `POST /rest/user/data-export` | IDOR, GDPR Data Theft | POST | ✅ |
| `/#/complain` (file upload) | File Upload Bypass (size & type) | POST | ✅ |
| B2B XML Upload | XXE, Deprecated Interface | POST | ✅ |
| `POST /rest/deluxe-membership` | Business Logic Bypass | POST | ✅ |
| `/i18n/{lang}.json` | Brute Force / Enumeration | GET | ✅ |
| Authorization Header (JWT) | JWT None Alg, RS256→HS256 | — | ⚠️ 需专用工具 |
| OAuth Login Flow | OAuth Implementation Flaw | POST | ⚠️ 需逻辑 |
| Support Chat (WebSocket) | Prompt Injection | WS | ❌ 不可自动扫描 |

---

## 五、扫描器能力评估参考

按漏洞类型预估主流 DAST 扫描器的典型检出能力：

| 漏洞类型 | 挑战数 | DAST 典型可检出 | 备注 |
|----------|--------|----------------|------|
| SQL Injection | 7 | 5-7 | 主流扫描器强项 |
| NoSQL Injection | 3 | 0-2 | 多数扫描器支持差 |
| XSS (DOM/Reflected/Stored) | 10 | 4-7 | DOM XSS 检出率低 |
| IDOR / BAC | 12 | 1-3 | 需业务逻辑理解 |
| File Upload Issues | 2 | 1-2 | 基本可检出 |
| XXE | 2 | 1-2 | 需要上传点发现 |
| Open Redirect | 3 | 2-3 | 检出率较高 |
| Directory Listing / Info Disclosure | 5+ | 3-5 | 检出率较高 |
| JWT Issues | 2 | 0-1 | 需专用工具 |
| Deserialization | 2 | 0-1 | 极难自动检出 |
| Security Misconfiguration | 4 | 2-3 | Error Handling / Deprecated |
| Weak Password / Brute Force | 5+ | 1-3 | 取决于扫描器配置 |
| OSINT / Social Engineering | 10+ | 0 | 不可自动扫描 |
| Business Logic | 5+ | 0-1 | 几乎不可自动检出 |
| Crypto Issues | 5 | 0-1 | 需 SCA 工具辅助 |

> **粗略预估**: 一款成熟的 DAST 扫描器在 Juice Shop 上的典型召回率约 **25%-40%**，主要覆盖 SQL Injection、XSS、Open Redirect、Info Disclosure 等传统漏洞，而 IDOR、业务逻辑、OSINT 类挑战几乎无法自动检出。

---

## 六、参考资源

- **官方 challenges.yml**: https://github.com/juice-shop/juice-shop/blob/master/data/static/challenges.yml
- **Pwning OWASP Juice Shop (在线阅读)**: https://pwning.owasp-juice.shop
- **Challenge Solutions (完整解题)**: https://pwning.owasp-juice.shop/companion-guide/latest/appendix/solutions.html
- **Juice Shop API**: 运行实例后访问 `/api/Challenges` 获取 JSON 格式挑战列表
- **Vulnerability Categories 映射表**: https://pwning.owasp-juice.shop/companion-guide/latest/part1/categories.html
