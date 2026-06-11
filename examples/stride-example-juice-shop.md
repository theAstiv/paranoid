# STRIDE Example: OWASP Juice Shop E-Commerce Platform

This example demonstrates threat modeling for the OWASP Juice Shop — an intentionally vulnerable e-commerce web application. Designed for use with the `--code` flag pointing at the [juice-shop/juice-shop](https://github.com/juice-shop/juice-shop) repository, so Paranoid can discover vulnerabilities directly from source code alongside the structured description.

---

## Component Description

```xml
<component_description>
```

**Name:** Juice Shop — Open-Source E-Commerce Web Application

**Purpose:** Single-page web application that lets customers browse a product catalogue, add items to a shopping basket, complete purchases with credit card or digital wallet, leave product reviews, and interact with a customer feedback system. Includes an admin section for order management, user administration, and a built-in challenge-tracking scoreboard. Designed as a realistic modern e-commerce platform.

**Technology Stack:**
- **Language(s):** TypeScript (backend + frontend), JavaScript
- **Framework(s):** Express.js (REST API), Angular (SPA frontend)
- **Libraries / SDKs:** Sequelize ORM (SQLite / MariaDB), jsonwebtoken (JWT auth), express-jwt, z85 (token encoding), sanitize-html, marsdb (in-memory MongoDB-like), socket.io (WebSocket for challenge notifications), libxmljs2 (XML parsing for B2B orders), swagger-ui-express
- **Database:** SQLite (default, file-based), MariaDB (optional production)
- **Cloud Infrastructure:** Self-hosted or Docker; no cloud-managed services assumed
- **Serving:** Node.js serves both API and pre-built Angular SPA from the same process

**Interfaces and Protocols:**
- Inbound Interfaces:
  - HTTPS REST API — Customer endpoints (`GET /api/Products`, `POST /api/BasketItems`, `POST /api/Orders`, `POST /api/Feedbacks`, `POST /api/Complaints`)
  - HTTPS REST API — User authentication (`POST /rest/user/login`, `POST /api/Users`, `GET /rest/user/whoami`, `POST /rest/user/reset-password`)
  - HTTPS REST API — Admin endpoints (`GET /api/Users`, `GET /api/Quantitys`, `DELETE /api/Recycles/:id`)
  - HTTPS REST API — File upload (`POST /file-upload`, `POST /profile/image/file`)
  - HTTPS REST API — B2B XML order intake (`POST /api/Orders`, XML Content-Type variant)
  - HTTPS REST API — Metrics and scoreboard (`GET /api/Challenges`, `GET /metrics`)
  - WebSocket — Real-time challenge-solved notifications via socket.io
  - Static file serving — Angular SPA, product images, FTP directory listing
- Outbound Interfaces:
  - None by default (self-contained); optional webhook for challenge notifications

**Data Handled:**
- **Sensitive Data Types:** User email addresses, bcrypt-hashed passwords, credit card numbers (stored for repeat purchases), security question answers (plain text), personal addresses, order history with item details and totals, product reviews (user-generated content), uploaded files (profile images, complaint attachments, order confirmation PDFs), JWT session tokens, CAPTCHA solutions, coupon codes
- **Storage Mechanisms:** SQLite database file (default) or MariaDB, filesystem for uploads (`/uploads`, `/ftp`), in-memory store for CAPTCHA and certain tokens

**Trust Level:**
- **Internal/External:** Internet-exposed web application; single-tier architecture (no separate backend network)
- **Authentication / Authorization Used:** JWT-based session tokens (HS256 symmetric signing with a configurable secret), role field embedded in JWT payload (`role: "customer"` or `role: "admin"`), no server-side session store, password reset via security question (no email verification), CAPTCHA on feedback form, basic rate limiting on login

**Dependencies:**
- SQLite or MariaDB (data persistence)
- Node.js runtime
- npm packages (~800 transitive dependencies)
- No external authentication provider (self-managed user store)
- No payment gateway integration (simulated checkout)

```xml
</component_description>
```

---

## Assumptions

```xml
<assumptions>
```

**Security Controls Already in Place:**
- Passwords hashed with bcrypt before storage
- JWT tokens used for session management
- CAPTCHA on customer feedback submission form
- Content Security Policy headers configured
- Helmet.js middleware for basic HTTP security headers
- sanitize-html applied to some user-generated content fields
- Rate limiting on authentication endpoints (basic)
- Swagger API documentation served at `/api-docs`

**Areas Considered In-Scope:**
- SQL injection across all Sequelize query paths (raw queries, parameterised queries, search endpoints)
- Cross-site scripting (reflected, stored, DOM-based) in product search, feedback, and user profile
- Broken authentication: JWT secret strength, token structure, role manipulation, password reset flow
- Broken access control: horizontal privilege escalation (accessing other users' baskets, orders, addresses), vertical escalation (customer → admin)
- Server-side request forgery via B2B XML order intake (XXE)
- Insecure file upload: unrestricted file types, path traversal in upload filenames
- Sensitive data exposure: credit card storage, security answers in plain text, verbose error messages, source map exposure
- Security misconfiguration: directory listing on `/ftp`, exposed metrics endpoint, default credentials, debug endpoints
- Injection beyond SQL: NoSQL injection in MongoDB-like stores, OS command injection via file operations, LDAP injection
- Broken anti-automation: CAPTCHA bypass, coupon brute-forcing, registration flooding
- Cryptographic failures: weak JWT secret, predictable tokens, insecure random number generation
- Prototype pollution in Node.js dependency chain

**Areas Considered Out-of-Scope:**
- Underlying OS and container runtime vulnerabilities
- Network infrastructure (load balancers, firewalls, DNS)
- Physical security of hosting environment
- Third-party npm package supply chain (dependency confusion, typosquatting) beyond known vulnerable versions
- Browser-side vulnerabilities unrelated to application code

**Known Constraints or Limitations:**
- JWT uses HS256 with a symmetric secret; secret strength depends on configuration
- No email verification for account registration or password reset
- Security question answers stored without hashing
- File upload directory is served statically with limited access control
- B2B order endpoint accepts XML input, enabling XXE if not properly configured
- CAPTCHA is only applied to the feedback form, not to login or registration
- Admin role is determined by a JWT claim that is set at login time
- No audit logging of administrative actions
- SQLite default has no network-level access control
- Coupon codes are validated client-side before server-side confirmation

**Development or Operational Considerations:**
- Open-source project with full source code publicly available
- Used extensively for security training, CTF competitions, and penetration testing practice
- Challenge scoreboard tracks exploitation progress — metadata about vulnerabilities is embedded in the application
- Swagger documentation at `/api-docs` exposes full API surface
- Prometheus metrics at `/metrics` may leak operational data
- FTP directory at `/ftp` serves miscellaneous files including encryption keys

**Threat Modeling Focus Areas:**
- SQL injection in product search and user login (both parameterised and raw query paths)
- JWT manipulation: algorithm confusion (none/HS256/RS256), secret brute-force, role claim tampering
- Horizontal privilege escalation between customer accounts (basket, order, address IDOR)
- Vertical privilege escalation from customer to admin role
- XXE via B2B XML order processing
- Stored XSS through product reviews, feedback, and user profile fields
- Sensitive data exposure: credit cards, security answers, error stack traces, source maps
- File upload abuse: web shell upload, path traversal, overwriting application files
- Directory traversal via `/ftp` and file-serving endpoints
- Broken password reset: security question enumeration, answer guessing
- Prototype pollution in Express.js middleware chain
- Information disclosure through `/metrics`, `/api-docs`, error responses, and `/ftp` directory

```xml
</assumptions>
```

---

## How to Use This Example

### With Code Context (Recommended)

```bash
# First, add the Juice Shop repo as a code source in the UI, or clone locally:
git clone --depth 1 https://github.com/juice-shop/juice-shop.git /tmp/juice-shop

paranoid run examples/stride-example-juice-shop.md \
  --code /tmp/juice-shop \
  --iterations 5 \
  --output juice-shop-threats.json
```

### Without Code Context

```bash
paranoid run examples/stride-example-juice-shop.md \
  --iterations 3 \
  --output juice-shop-threats.json
```

### Expected Output

The pipeline will generate threats covering all STRIDE categories, with code-backed evidence when `--code` is used:

- **Spoofing**: JWT algorithm confusion (none attack), forged admin tokens, security-question-based account takeover
- **Tampering**: SQL injection in search/login, prototype pollution in Express middleware, coupon code manipulation, basket item price tampering
- **Repudiation**: No audit trail for admin actions, missing logging on password resets, order modification without trace
- **Information Disclosure**: Credit card exposure, security answer leakage, verbose error stack traces, source map exposure, `/ftp` directory listing, `/metrics` data, Swagger docs
- **Denial of Service**: Registration flooding without CAPTCHA, file upload storage exhaustion, CPU-intensive XML parsing (billion laughs)
- **Elevation of Privilege**: JWT role claim tampering (customer → admin), IDOR on basket/order/address endpoints, admin panel access via direct URL

---

## Notes

- This is an intentionally vulnerable application — every security audience knows it
- Running Paranoid with `--code` against Juice Shop and showing it auto-discover the same OWASP Top 10 vulns the app was designed around is a compelling demo
- The code context lets Paranoid find concrete injection points (specific route handlers, raw SQL queries, weak JWT config) rather than generic threat categories
