# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.5.x   | Yes       |
| < 1.5   | No        |

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
- **Personal Access Tokens (PATs)**: `pat_<id>_<random>` format, sha256-hashed before storage, returned raw only on creation
- **PAT and git credential encryption**: Fernet (AES-128-CBC + HMAC-SHA256); key derived from `CONFIG_SECRET` via PBKDF2-HMAC-SHA256 (100k iterations); falls back to a random file key at `data/.source_key`
- **Login rate limiting**: 10 requests per 60 seconds per IP
- **CSRF protection**: `ALLOWED_ORIGINS` enforced on all state-mutating requests
- **Git clone hardening**: `protocol.file.allow=never`, `core.symlinks=false`, `GIT_TERMINAL_PROMPT=0`, HTTPS-only, host allowlist

Raw credentials are never logged, never returned by any API endpoint (PAT presence is reported as `has_pat: bool` only), and never included in SSE event payloads.
