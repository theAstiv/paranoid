# Configuration

Paranoid is configured via environment variables. Set them in `.env` (Docker) or export them before running the CLI.

## Quick reference

```bash
cp .env.example .env
# Edit .env, then:
docker compose up --build
```

---

## Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Anthropic (Claude) API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama server URL |
| `DEFAULT_PROVIDER` | `anthropic` | Active provider: `anthropic`, `openai`, `ollama` |
| `DEFAULT_MODEL` | `claude-sonnet-4-20250514` | Default model name |
| `FAST_MODEL` | `claude-haiku-4-5-20251001` | Haiku-class model for extraction/enrichment steps (Anthropic only); set to same as `DEFAULT_MODEL` to disable fast routing |

**Recommended models by provider:**

| Provider | Recommended | Notes |
|----------|-------------|-------|
| Anthropic | `claude-sonnet-4-20250514` | Best balance of quality and speed |
| OpenAI | `gpt-4o` | Required for vision (`--diagram`) support |
| Ollama | `llama3.1:8b`, `qwen2.5:14b` | Need 32K+ context window |

---

## Pipeline

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_ITERATIONS` | `3` | Iteration passes (1–15) |
| `MAX_ITERATION_COUNT` | `15` | Hard maximum (validation at startup) |
| `MIN_ITERATION_COUNT` | `1` | Hard minimum |
| `MIN_ITERATIONS` | `1` | Minimum iterations before any early-stop condition (gap satisfied, dedup saturation) can fire |
| `DEDUP_SATURATION_THRESHOLD` | `0.7` | Stop when ≥ this fraction of new threats in an iteration are cross-iteration duplicates (0.0–1.0) |
| `DEFAULT_TEMPERATURE` | `0.2` | LLM sampling temperature |
| `PIPELINE_TIMEOUT_MINUTES` | `30` | Per-run pipeline timeout |

---

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `./data/paranoid.db` | SQLite database file path |

---

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warn`, `error` |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated); use `*` for all |

---

## Security and auth

| Variable | Default | Description |
|----------|---------|-------------|
| `PARANOID_REQUIRE_AUTH` | `false` | `false` = anonymous admin mode; `true` = require login |
| `PARANOID_ADMIN_PASSWORD` | random | Password for the auto-created `admin` account on first startup; if unset, a random password is generated and logged once |
| `JWT_SECRET` | derived | JWT signing key; falls back to `PBKDF2(CONFIG_SECRET)`, then an ephemeral per-process key |
| `CONFIG_SECRET` | — | Optional shared secret protecting `PATCH /api/config` (Settings page) and used as PAT encryption key source |
| `ALLOWED_ORIGINS` | `localhost:8000` | Concrete origins for CSRF protection; set to your deployment origin(s) when exposing beyond localhost |

> **Docker port binding note:** The default `docker-compose.yml` binds to `127.0.0.1:8000` (loopback only). For LAN or public access, change to `"0.0.0.0:${PORT:-8000}:8000"` **and** set `ALLOWED_ORIGINS` to your public origin.

---

## Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model for vector search (baked into Docker image at build time) |
| `SIMILARITY_THRESHOLD` | `0.85` | Cosine similarity threshold for threat deduplication |
| `RAG_TOP_K` | `10` | Top-K results from vector search per pipeline step |

---

## Advanced

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTEXT_LINK_BINARY` | auto | Explicit path to the `context-link` binary; if unset, Paranoid searches `./bin/context-link` then `PATH` |
| `ADDITIONAL_GIT_HOSTS` | — | Extra git clone hosts beyond `github.com`, `gitlab.com`, `bitbucket.org`; comma-separated exact hostnames (no wildcards); e.g. `git.company.com,git.internal.net` |
| `SEED_COLLECTIONS` | all 16 | Comma-separated subset of rule engine seed collections to load; unknown names raise a startup error; e.g. `stride,auth,cloud` |

---

## Precedence

1. **CLI flags** (`--provider anthropic`) — highest priority, per-run only
2. **Environment variables** (`.env` or shell exports)
3. **Config file** (`~/.paranoid/config.json`, written by `paranoid config init`)
4. **Built-in defaults** — lowest priority

---

## Docker Compose secrets note

Use `env_file: .env` in `docker-compose.yml` for API keys — **not** `environment: ${VAR}` interpolation. Compose silently truncates long values during variable interpolation, which breaks API keys.

```yaml
# Correct
services:
  app:
    env_file: .env

# Risky — long values may be truncated
services:
  app:
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```
