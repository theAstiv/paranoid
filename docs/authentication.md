# Authentication and Multi-User Setup

Paranoid supports both anonymous single-user mode and full multi-user mode with JWT sessions, personal access tokens (PATs), and project-level RBAC.

## Modes

### Anonymous mode (default)

```bash
PARANOID_REQUIRE_AUTH=false   # default
```

Anyone with network access is treated as an instance admin. All routes are accessible without login. Suitable for local development or single-user self-hosted deployments.

### Auth mode

```bash
PARANOID_REQUIRE_AUTH=true
```

Users must log in before accessing any resource. The auto-created `admin` account is the first user. Registration is open: anyone who can reach the server can create an account (rate-limited to 5 per minute per client IP). A new account sees no existing project until an owner adds it, but it can create projects of its own and run models in them on the instance's provider keys. There is no setting to turn registration off, so don't expose an auth-on instance to networks whose users shouldn't have accounts.

### Requirements: HTTPS or localhost

With auth on, serve Paranoid over **HTTPS**, or use it only through `localhost`.

The browser keeps you signed in with a refresh token in a `Secure` cookie. Browsers never store a `Secure` cookie from a plain `http://` page; Chrome and Firefox make an exception only for `localhost` and loopback addresses (`127.0.0.1`, `[::1]`). On `http://` with any other host — a LAN IP like `http://192.168.1.20:8000` or a name like `http://paranoid.internal` — login works, but the cookie is dropped, so the first refresh fails and every user is sent back to the login page when their 15-minute access token expires.

- Put Paranoid behind a TLS-terminating reverse proxy (see [Deployment](deployment.md)) and set `ALLOWED_ORIGINS` to the `https://` origin.
- At startup, with `PARANOID_REQUIRE_AUTH=true`, the server logs a warning for every `http://` origin in `ALLOWED_ORIGINS` whose host isn't loopback.
- API clients (CLI, scripts, CI) are not affected: they send the refresh token in the request body or use a PAT.

The cookie is deliberately not downgraded on plain HTTP: anyone on the same network could read it and keep the session alive for 7 days.

---

## First-time setup

When the server starts with a fresh database, it creates an `admin` user automatically:

```bash
# Set a known password (otherwise a random one is generated and logged once)
PARANOID_ADMIN_PASSWORD=your-admin-password docker compose up
```

Log in at `http://localhost:8000/app#/login` with username `admin` and the configured password.

If `PARANOID_ADMIN_PASSWORD` is unset, the generated password is written to the server log once, so anyone who can read your container logs or log aggregator can read it. For any shared deployment, set `PARANOID_ADMIN_PASSWORD` and rotate the password after first login.

---

## Account management

### Register

`POST /api/auth/register` — open to anyone who can reach the server; 5 per minute per client IP (`429` with `Retry-After` beyond that).

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "secure-passphrase"
}
```

### Login

`POST /api/auth/login` — returns a JWT access token (short-lived) and a refresh token (HttpOnly cookie for browsers; also returned in the response body for CLI use).

### Update profile

`PATCH /api/auth/me` — update display name or password.

A password change (`current_password` + `password`) ends all of the user's other sessions: their refresh tokens stop working at once, and access tokens they already hold expire within their 15 minutes. The browser session that made the change (its refresh cookie) stays signed in; a caller using only a bearer token has no session to keep and logs in again with the new password. PATs are not affected; delete them separately if they may be exposed.

---

## JWT lifecycle

- **Access token**: short-lived (default 15 min), sent as `Authorization: Bearer <token>` header
- **Refresh token**: long-lived (default 7 days), rotated on every use (reuse detection included)
  - Browser: HttpOnly, SameSite=Strict, Secure cookie on `Path=/api/auth/`
  - CLI / body fallback: also returned in the response body as `refresh_token`

```bash
# CLI login flow
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"secret"}' | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/models
```

---

## Personal Access Tokens (PATs)

PATs are long-lived tokens for CLI and CI/CD use — no session management needed.

### Create a PAT

```bash
curl -X POST http://localhost:8000/api/auth/tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline", "expires_in_days": 365}'
```

The raw token is returned **once** — store it securely.

Add `"project_id": "<id>"` to limit the token to one project (you must belong to it). A project-scoped token can only act inside that project, **even if you are an instance admin**. It cannot create projects, create models in other projects, or create, list or revoke tokens. Without `project_id` the token has all your memberships. Limits: code-source list/create and your notifications are not filtered by the token's project.

### Use a PAT

```bash
curl -H "Authorization: Bearer pat_xxxx" http://localhost:8000/api/models
```

PATs authenticate HTTP API clients (scripts, CI jobs calling the REST API). The `paranoid` CLI doesn't talk to a remote server yet: it runs the pipeline locally and reads and writes its own database (`DB_PATH`), so it has no `--token` flag or `PARANOID_TOKEN` variable.

### List and revoke PATs

```bash
# List (metadata only, no token hashes)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/tokens

# Revoke by ID
curl -X DELETE http://localhost:8000/api/auth/tokens/<token_id> \
  -H "Authorization: Bearer $TOKEN"
```

---

## Project roles (RBAC)

Every threat model belongs to a project. Access to a threat model is governed by the user's role in that project.

| Role | Can do |
|------|--------|
| **Viewer** | Read threat models, view comments |
| **Editor** | Everything Viewer can do, plus run pipelines, approve/reject threats, add comments, edit context |
| **Owner** | Everything Editor can do, plus invite/remove members, change project settings, delete the project |

The instance `admin` user has admin access to all projects.

### Invite a user

Owners can invite users to a project via the **Members** page in the web UI, or via the API:

```bash
POST /api/projects/{project_id}/members
{
  "user_id": "...",
  "role": "editor"
}
```

### Change a role

```bash
PATCH /api/projects/{project_id}/members/{user_id}
{
  "role": "viewer"
}
```

---

## Instance admin

Users with `is_admin=true` can access the **Admin** section of the web UI (`#/admin/users`) to:
- List all users
- Promote/demote admin status
- Deactivate accounts

The `admin` user created at startup has `is_admin=true` by default.

---

## PAT encryption

PATs and git clone credentials (personal access tokens for private repos) are Fernet-encrypted before being written to SQLite:

- **Key derivation**: `CONFIG_SECRET` env var → PBKDF2-HMAC-SHA256 (100k iterations, 32-byte key)
- **Fallback**: random 32-byte key stored at `data/.source_key` (mode 0600) if `CONFIG_SECRET` is unset
- Raw secrets are never logged, never returned by the API (`has_pat: bool` only), and never included in SSE events
- **Warning**: rotating `CONFIG_SECRET` after PATs have been stored will invalidate all stored credentials

---

## CSRF protection

The `ALLOWED_ORIGINS` env var sets the list of trusted origins for CSRF checks on state-mutating requests. Default: `localhost:8000`.

```bash
# Single deployment origin
ALLOWED_ORIGINS=https://paranoid.yourcompany.com

# Multiple origins
ALLOWED_ORIGINS=https://paranoid.company.com,https://paranoid-staging.company.com
```
