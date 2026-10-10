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
| `AWS_REGION` | — | AWS region for the Bedrock provider; empty lets boto3 resolve it via env/profile/instance metadata |
| `AWS_PROFILE` | — | AWS named profile for Bedrock; empty uses boto3's default credential chain |
| `DEFAULT_PROVIDER` | `anthropic` | Active provider: `anthropic`, `openai`, `ollama`, `bedrock` |
| `DEFAULT_MODEL` | `claude-sonnet-4-20250514` | Default model name |
| `ANTHROPIC_EFFORT` | — | Optional `low`/`medium`/`high`/`xhigh`/`max`; sent as `output_config.effort` to the **main** Anthropic model only (never the fast model). Unset keeps the model default. `claude-sonnet-5` at its default overran 4096 tokens on threat JSON; `medium` finished. Older models (e.g. Haiku 4.5) reject it — the provider then retries once without it |
| `FAST_MODEL` | `claude-haiku-4-5-20251001` | Haiku-class model for extraction/enrichment steps when `DEFAULT_PROVIDER=anthropic`; set to `""` (or the same value as `DEFAULT_MODEL`) to disable fast routing |
| `FAST_MODEL_OPENAI` | `gpt-4.1-mini` | Fast model when `DEFAULT_PROVIDER=openai`. **Behaviour change:** before week 4a-2, fast routing only existed for Anthropic — existing OpenAI users now get `gpt-4.1-mini` for extraction and enrichment steps by default. Set to the same value as `DEFAULT_MODEL`, or to `""`, to disable it |
| `FAST_MODEL_BEDROCK` | — (disabled) | Fast model when `DEFAULT_PROVIDER=bedrock`. Empty by default — a Bedrock model ID can't be verified without live AWS credentials, so there's no safe default to ship |
| `FAST_MODEL_OLLAMA` | — (disabled) | Fast model when `DEFAULT_PROVIDER=ollama`. Empty by default (same as main) |
| `STEP_MODELS` | `{}` | JSON object overriding which pipeline steps use the fast vs. main model, e.g. `STEP_MODELS={"extract_flows":"main"}`. Keys: `summarize`, `summarize_code`, `extract_assets`, `extract_flows`, `generate_attack_tree`, `generate_test_cases` (and `generate_threats`/`gap_analysis`, which may only be set to `"main"` — routing either to the fast model is rejected at startup). Merges onto the active provider's default map; a step left out keeps its default. Invalid steps or values fail at startup, not on the first pipeline run |
| `BEDROCK_IMAGE_MODELS` | — (built-in default) | Comma-separated list of Bedrock model-ID substrings that accept images. **Replaces** the built-in default entirely rather than extending it — include the defaults you still want alongside any addition, e.g. `BEDROCK_IMAGE_MODELS=anthropic.claude,amazon.nova-pro,amazon.nova-lite,<your-vision-model>`. Empty (default): Claude and the vision-capable Nova sizes (Pro/Lite/Premier, not Micro) take images, every other Bedrock model (gpt-oss, Qwen, DeepSeek, Llama text variants, …) is treated as text-only and gets the same `vision_unsupported` degrade as the Ollama provider. An application inference profile ARN, or any model ID that doesn't contain `anthropic.claude`/`amazon.nova-*`, is treated as text-only unless it's added here — the `vision_unsupported` event names the model, so this is visible rather than a silent 400 |

A step routed to the fast model that fails with a non-transient error (anything other than a rate limit, timeout, connection error or 5xx / "overloaded" response — an auth failure, an unknown/inaccessible model, a bad request) disables fast routing for the rest of that run; later steps, and later per-threat enrichment calls under `--enrich`, go straight to the main model instead of each paying a failed call first. Such a run is flagged: its usage summary has `fast_routing_disabled: true`, the CLI summary prints a warning, and the Results page's Run Summary shows a "fast routing disabled mid-run" chip — its token split doesn't reflect the configured routing.

**Changing routing without editing the environment:**

- **CLI, per run:** `--fast-model <id>` overrides the active provider's fast model; `--fast-model=` (the `=` form — an empty value after a bare space is swallowed by PowerShell before it reaches the program) runs every step on the main model. `--step-model STEP=fast|main` (repeatable) replaces `STEP_MODELS` for that run. See the [CLI reference](cli-reference.md).
- **Settings page:** the *Fast model* field edits the fast model of the provider selected above it (`FAST_MODEL`, `FAST_MODEL_OPENAI`, `FAST_MODEL_BEDROCK` or `FAST_MODEL_OLLAMA`). Leave it empty to turn routing off for that provider. Like the other non-key settings it is held in memory and resets to the environment value on restart.

The Run Summary on the Results page lists each step's model and its input / output / cache-read / cache-write tokens, so you can see what the fast model actually served. For CLI runs, the usage summary also includes a `pre_flight` row when the description/assumptions gap check made an LLM call (it often doesn't — deterministic checks skip it when they already found enough signal), so pre-flight spend isn't dropped from the run's totals.

**Recommended models by provider:**

| Provider | Recommended | Notes |
|----------|-------------|-------|
| Anthropic | `claude-sonnet-4-20250514` | Best balance of quality and speed |
| OpenAI | `gpt-4o` | Required for vision (`--diagram`) support |
| Ollama | `llama3.1:8b`, `qwen2.5:14b` | Need 32K+ context window |
| Bedrock | Anthropic Claude models via Bedrock | Uses your existing AWS credential chain — no separate API key. Retries `converse()` without `temperature` on providers that reject it. |

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

## Dependency capability engine

| Variable | Default | Description |
|----------|---------|-------------|
| `SEMGREP_BINARY` | auto | Explicit path to the `semgrep` binary; if unset, Paranoid searches `PATH`. Semgrep is not a Python dependency of Paranoid — install it separately (`pip install semgrep` or `pipx install semgrep`) |
| `DEPS_CACHE_DIR` | `./data/deps_cache` | Per-version cache for fetched npm tarball / GitHub source trees. A given version's entry is immutable while present, but the cache as a whole is no longer unbounded — see `DEPS_CACHE_MAX_GB` |
| `DEPS_MAX_TARBALL_MB` | `50` | Compressed-size cap enforced during download, before extraction |
| `DEPS_ANALYSIS_TIMEOUT_SECONDS` | `180` | Wall-clock budget for the pipeline's dependency-analysis step; exceeding it degrades to a warning and the pipeline continues without it. Individual packages are budgeted against this deadline, so a cold-cache run returns whatever finished instead of discarding the whole sweep |
| `DEPS_ANALYSIS_ENABLED` | `true` | Kill switch for server-side dependency analysis via `POST /api/models/{id}/run` (manifest upload and code-source auto-detect). `false` rejects an uploaded manifest with 422 and skips auto-detect, without a redeploy. Does not affect the `paranoid deps`/`paranoid run --manifest` CLI |
| `DEPS_MAX_CONCURRENT_SCANS` | `2` | Process-wide cap on concurrent Semgrep subprocesses, across every simultaneous pipeline run sharing this process (separate from the 4-at-a-time limit applied within one manifest's sweep) |
| `DEPS_CACHE_MAX_GB` | `10` | Soft size budget for `DEPS_CACHE_DIR`, in GiB. Checked after every fetch; the least-recently-used entries (by last access, not just last fetch) are deleted first, skipping anything currently being fetched, scanned, or drift-compared. `0` disables eviction entirely |

See [Dependency capability engine](../README.md#dependency-capability-engine) in the README for what `paranoid deps scan|diff|scan-manifest` report and their limits.

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
