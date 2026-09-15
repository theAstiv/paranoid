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

Users must log in before accessing any resource. The auto-created `admin` account is the first user; all others self-register unless registration is restricted.

---

## First-time setup

When the server starts with a fresh database, it creates an `admin` user automatically:

```bash
# Set a known password (otherwise a random one is generated and logged once)
PARANOID_ADMIN_PASSWORD=your-admin-password docker compose up
```

Log in at `http://localhost:8000/app#/login` with username `admin` and the configured password.

---

## Account management

### Register

`POST /api/auth/register`

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

### Use a PAT

```bash
# CLI — environment variable
export PARANOID_TOKEN=pat_xxxx
paranoid models list

# CLI — flag
paranoid models list --token pat_xxxx

# Direct HTTP
curl -H "Authorization: Bearer pat_xxxx" http://localhost:8000/api/models
```

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
