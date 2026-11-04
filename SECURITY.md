# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.6.x   | Yes       |
| < 1.6   | No        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email: **astivhuman66@gmail.com**

Include in your report:
- Description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept
- Affected version(s)
- Any suggested mitigations (optional)

You will receive an acknowledgement within **48 hours** and a status update
within **7 days**. If the issue is confirmed, a patch will be prioritised and
you will be credited in the release notes (unless you prefer to remain
anonymous).

## Scope

In scope:
- The FastAPI backend (`backend/`)
- The Svelte frontend (`frontend/`)
- The CLI (`cli/`)
- The GitHub Action (`action/`)
- Authentication and authorisation logic (`backend/auth/`)
- Code-source clone pipeline and PAT handling (`backend/sources/`)

Out of scope:
- Vulnerabilities in third-party dependencies (report to the upstream project)
- Issues requiring physical access to the host machine
- Social engineering attacks

## Threat model notes

Paranoid is a self-hosted, multi-user threat modeling tool. The operator
controls the host environment and network access. The security model depends on
your deployment configuration:

**`PARANOID_REQUIRE_AUTH=false` (default):** Anyone with network access is
treated as an instance admin. This is appropriate for local development or
single-user self-hosted use — do not expose this configuration to untrusted
networks.

**`PARANOID_REQUIRE_AUTH=true`:** Full authentication required. Users must
register and log in before accessing any resource.

### Auth attack surface

- **Passwords**: argon2id hashing via `argon2-cffi` (lazy-imported, does not affect CLI cold start)
- **Sessions**: HS256 JWT access tokens (15-minute lifetime) + refresh tokens (7-day lifetime, rotated on every use)
- **Refresh token reuse detection**: a stolen refresh token is usable exactly once — reuse revokes the entire session family
- **Refresh token check**: a refresh token is `<session id>:<secret>`; the server stores only a SHA-256 of the whole token and compares it in constant time before anything else, so knowing a session id is not enough, and a forged token can't trigger the reuse revocation
- **Project owners**: removing or demoting a project's last owner is refused (`409`), whichever route changes the role, and the check and the change are one transaction. Removing a member also deletes their assignments and notifications in that project
- **Project-scoped tokens and notifications**: a PAT scoped to a project lists and marks only that project's notifications
- **Personal Access Tokens (PATs)**: `pat_<id>_<random>` format, sha256-hashed before storage, returned raw only on creation
- **PAT and git credential encryption**: Fernet (AES-128-CBC + HMAC-SHA256); key derived from `CONFIG_SECRET` via PBKDF2-HMAC-SHA256 (100k iterations); falls back to a random file key at `data/.source_key`
- **Rate limiting** (per client IP; `X-Forwarded-For` only from `TRUSTED_PROXIES`): login and refresh 10 per minute; registration 5 per minute, in its own bucket; LLM-backed routes (pre-flight `/api/analyze`, a model's `/analyze` and `/extract`, attack trees, test cases) 20 per minute; pipeline runs 5 per minute. Counters are per process and reset on restart
- **Open registration**: anyone who can reach an auth-on server can create an account. It sees no existing project until an owner adds it, but it can create its own projects and run models there on the instance's provider keys. There is no switch to disable registration, so limit network exposure accordingly
- **Refresh cookie**: HttpOnly, `SameSite=Strict`, `Secure`, `Path=/api/auth/`. Auth on therefore needs HTTPS or `localhost` (browsers drop a `Secure` cookie on other plain-HTTP origins); the server warns at startup about plain-HTTP `ALLOWED_ORIGINS`
- **Access token storage**: the web UI keeps the 15-minute access token in `localStorage`, so script running in the page (XSS) could read it. Mitigations: CSP `script-src 'self'`, no `{@html}` in the UI, Mermaid sanitized and rendered with `securityLevel: 'strict'`. The refresh token is not readable from script
- **CSRF protection**: `ALLOWED_ORIGINS` enforced on all state-mutating requests
- **CORS**: `CORS_ORIGINS=*` (default) allows any origin **without** credentials; only a concrete origin list allows credentialed cross-origin requests, and only from those origins
- **Configuration endpoint**: `GET /api/config` requires a login when auth is on; API key values are never returned, only whether each is set and where from
- **Git clone hardening**: `protocol.file.allow=never`, `core.symlinks=false`, `GIT_TERMINAL_PROMPT=0`, HTTPS-only, host allowlist

Raw credentials are never logged, never returned by any API endpoint (PAT presence is reported as `has_pat: bool` only), and never included in SSE event payloads.
