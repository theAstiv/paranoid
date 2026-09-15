# REST API Reference

The Paranoid API is a FastAPI app served at `/api`. Interactive OpenAPI docs are available at `http://localhost:8000/docs` when the server is running.

## Authentication

All routes accept a bearer token in the `Authorization` header:

```
Authorization: Bearer <jwt-or-pat>
```

When `PARANOID_REQUIRE_AUTH=false` (default), all routes are accessible without authentication — the caller is treated as the instance admin.

---

## Models

### `GET /api/models`

List threat models. Returns most recent first.

**Query params:** `limit` (int, default 20), `offset` (int), `project_id` (UUID)

**Response:** `[ThreatModel]`

### `POST /api/models`

Create a new threat model record (without running the pipeline).

**Body:**

```json
{
  "title": "My system",
  "description": "...",
  "framework": "STRIDE",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "iterations": 3,
  "project_id": "uuid"
}
```

### `GET /api/models/{id}`

Get a threat model with its threats, assets, flows, and trust boundaries.

### `PATCH /api/models/{id}`

Update model metadata (title, status, assignees).

**Body:** `UpdateModelRequest` — any subset of title, status, assignee_ids

### `DELETE /api/models/{id}`

Delete a threat model and all its data. Owner or admin only.

### `POST /api/models/{id}/run`

Run (or re-run) the pipeline. Returns an SSE stream of `PipelineEvent` objects.

**Body (multipart/form-data):**

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string | Override provider for this run |
| `model` | string | Override model |
| `iterations` | int | Override iteration count |
| `framework` | string | `STRIDE`, `MAESTRO`, or `BOTH` |
| `diagram` | file | Architecture diagram (PNG, JPG, or .mmd) |
| `code_source_id` | string | UUID of a ready code source |

**SSE event format:**

```
data: {"step": "summarize", "status": "started", "message": "Generating summary..."}
data: {"step": "generate_threats", "iteration": 1, "status": "completed", "threats_count": 12}
data: {"step": "complete", "status": "completed", "total_threats": 23}
```

### `GET /api/models/{id}/context`

Get extracted context (assets, flows, trust boundaries) for editing before or after a run.

### `POST /api/models/{id}/re-extract`

Re-run only the extraction steps (summarize, extract_assets, extract_flows) without regenerating threats.

### `GET /api/models/{head_id}/diff`

Compare two models by embedding similarity.

**Query params:** `base_id` (UUID, required)

---

## Threats

### `GET /api/threats`

List threats, optionally filtered.

**Query params:** `model_id`, `status`, `category`, `limit`, `offset`

### `GET /api/threats/{id}`

Get a single threat with full DREAD scores, mitigations, and enrichment.

### `PATCH /api/threats/{id}`

Update a threat (status, DREAD scores, notes).

**Body:** `UpdateThreatRequest` — status, dread scores, notes, assignee_ids

### `POST /api/threats/{id}/approve`

Approve a threat (moves to `approved` status).

### `POST /api/threats/{id}/reject`

Reject a threat (moves to `rejected` status).

### `POST /api/threats/bulk`

Bulk status update for multiple threats.

**Body:**

```json
{
  "threat_ids": ["uuid1", "uuid2"],
  "status": "approved"
}
```

---

## Export

### `GET /api/models/{id}/export`

Export a saved model.

**Query params:** `format` — `json`, `full`, `sarif`, `markdown`, `pdf`

**Response:** File download with appropriate `Content-Type`.

---

## Configuration

### `GET /api/config`

Get current runtime configuration (provider, model, iterations, etc.).

### `PATCH /api/config`

Update runtime configuration. If `CONFIG_SECRET` is set, requires `X-Config-Secret` header.

**Body:**

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "iterations": 5
}
```

---

## Auth

### `POST /api/auth/register`

Create a new user account.

**Body:** `{"username": "alice", "email": "alice@example.com", "password": "..."}`

### `POST /api/auth/login`

Authenticate and receive JWT + refresh token.

**Body:** `{"username": "alice", "password": "..."}`

**Response:** `{"access_token": "...", "refresh_token": "...", "token_type": "bearer"}`

### `POST /api/auth/refresh`

Rotate the refresh token. Detects reuse.

### `POST /api/auth/logout`

Revoke the current refresh session.

### `GET /api/auth/me`

Current user profile.

### `PATCH /api/auth/me`

Update display name or password.

### `POST /api/auth/tokens`

Create a PAT. Returns the raw token once.

**Body:** `{"name": "ci", "expires_in_days": 365}`

### `GET /api/auth/tokens`

List PATs (metadata only — no raw tokens).

### `DELETE /api/auth/tokens/{token_id}`

Revoke a PAT.

---

## Projects

### `GET /api/projects`

List projects the current user is a member of.

### `POST /api/projects`

Create a project.

**Body:** `{"name": "My Project", "description": "..."}`

### `GET /api/projects/{id}`

Get project with member list.

### `PATCH /api/projects/{id}`

Update project settings (name, description, default provider/model/iterations).

### `DELETE /api/projects/{id}`

Delete a project and all its models. Owner or admin only.

### `GET /api/projects/{id}/members`

List project members with roles.

### `POST /api/projects/{id}/members`

Invite a user to the project.

**Body:** `{"user_id": "uuid", "role": "editor"}`

### `PATCH /api/projects/{id}/members/{user_id}`

Change a member's role.

### `DELETE /api/projects/{id}/members/{user_id}`

Remove a member from the project.

---

## Comments

### `GET /api/comments`

List comments. Filter by `model_id`, `threat_id`, or `entity_id`.

### `POST /api/comments`

Add a comment to a model, threat, or entity.

**Body:**

```json
{
  "model_id": "uuid",
  "threat_id": "uuid",
  "body": "Have we considered the API gateway bypass?"
}
```

### `PATCH /api/comments/{id}`

Edit a comment (author only).

### `DELETE /api/comments/{id}`

Delete a comment (author or owner).

---

## Sources (Code Sources)

### `GET /api/sources`

List code sources.

### `POST /api/sources`

Add and clone a git repository.

**Body:**

```json
{
  "name": "My Repo",
  "git_url": "https://github.com/org/repo.git",
  "ref": "main",
  "pat": "ghp_xxx"
}
```

**Response:** `202 Accepted` — clone runs as a background task; track progress via SSE.

### `GET /api/sources/{id}/events`

SSE stream of clone and index progress events.

### `POST /api/sources/{id}/reindex`

Re-clone and re-index a source.

### `DELETE /api/sources/{id}`

Delete a source and its clone directory.

---

## Notifications

### `GET /api/notifications`

List notifications for the current user.

### `POST /api/notifications/{id}/read`

Mark a notification as read.

### `POST /api/notifications/read-all`

Mark all notifications as read.

---

## Dashboard

### `GET /api/dashboard`

Aggregate statistics: total models, open threats by severity, recent activity, and "assigned to you" items.

---

## Analysis

### `POST /api/analyze`

Run the pre-flight gap analysis on a description without starting the full pipeline.

**Body:** `{"description": "...", "framework": "STRIDE"}`

**Response:** `AnalyzeDescriptionResponse` — list of gaps with severity and suggestions.
