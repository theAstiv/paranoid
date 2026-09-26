# Contributing to Paranoid

## Dev environment setup

**Backend:**

```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid
pip install -e ".[dev]"
uvicorn backend.main:app --reload   # http://localhost:8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

**With Docker (full stack):**

```bash
cp .env.example .env   # add at least one API key
docker compose up --build
```

**Run the test suite:**

```bash
# Full CI check (run this before every PR)
ruff check backend/ cli/ tests/
ruff format --check backend/ cli/ tests/
pytest tests/ -v --tb=short --ignore=tests/test_pipeline_e2e.py
npm test --prefix frontend
npm run build --prefix frontend
```

See [TESTING.md](TESTING.md) for details on the test suite and CI jobs.

**Windows notes for the dependency capability engine** (`backend/deps/`):

- Run Semgrep rule-fixture tests via `pytest tests/test_deps_rules.py -v`, not
  a one-shot `semgrep --test` — concurrent Semgrep invocations racing on the
  same `settings.yml` is a real failure mode on this platform, and the
  pytest wrapper avoids it.
- Enable the `LongPathsEnabled` registry key
  (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`) and point
  `DEPS_CACHE_DIR` at a short path (e.g. `C:\deps-cache`) before scanning
  real monorepos (Babel, Jest) — otherwise their extracted trees trip the
  classic 260-character `MAX_PATH` limit even after scoped extraction
  narrows it to one package's subdirectory.
- The live benchmark (`pytest -m live tests/live/test_deps_benchmark.py -v`)
  hits the real npm registry and `codeload.github.com` for ~40 packages and
  runs real Semgrep — it's excluded from the default test run
  (`-m "not live"` in `pyproject.toml`) and can take several minutes.
  Requires the Semgrep binary; skips automatically if it isn't installed.

---

## Branch and PR workflow

1. Fork the repo and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Keep commits small and focused — one logical change per commit.
3. Write tests for new behavior. See [TESTING.md](TESTING.md) for where to put them.
4. Run the full CI checklist (see above) before pushing.
5. Open a PR against `main`. GitHub Actions runs all CI jobs automatically.
6. All CI jobs must be green before merge.

**Commit convention:** `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`

```
feat: add gap_analysis node to pipeline
fix: prevent truncated JSON output from OpenAI provider
docs: add authentication guide
```

**Never push directly to `main`.** All work lands via PR.

---

## Where to add things

### New LLM provider

1. Create `backend/providers/new_provider.py`
2. Implement the `LLMProvider` protocol from `backend/providers/base.py` — one method: `generate_structured(prompt, response_model, max_tokens)`
3. Register in `backend/providers/__init__.py`
4. Add the provider name to `backend/config.py` and `backend/models/enums.py`
5. Add env var(s) to `backend/config.py` and `.env.example`
6. Write tests in `tests/test_providers_new_provider.py` — mock all HTTP calls

### New pipeline step

1. Add an `async def` function in `backend/pipeline/nodes/`
2. Accept and return Pydantic models from `backend/models/`
3. Wire it into `backend/pipeline/runner.py` and add an SSE event type
4. Write tests — one with mock provider returning valid output, one with malformed output

### New export format

1. Create `backend/export/new_format.py`
2. Add a route in `backend/routes/export.py`
3. Add a CLI option in `cli/main.py`
4. Write tests in `tests/test_export_new_format.py`

### New frontend page

1. Create `frontend/src/routes/NewPage.svelte`
2. Add the route in `App.svelte` — all authenticated routes automatically get chrome (sidebar + topbar)
3. Add API calls to `frontend/src/lib/api.js` (stub missing endpoints that return `[]` or `{}`)
4. Add stores to `frontend/src/lib/stores.js` if shared state is needed
5. **Read [docs/frontend-design.md](docs/frontend-design.md)** before writing any styles — it documents the design token system, spacing rules, and component classes. Use `c-*` color tokens from `tailwind.config.js`, `chip-*` classes, and `.btn-primary` / `.btn-ghost` from `app.css`

### New seed patterns

Add entries to the appropriate file in `seeds/`. Embeddings regenerate on next startup. Pattern files use this structure:

```json
[
  {
    "name": "Pattern Name",
    "category": "Tampering",
    "description": "...",
    "target": "component type",
    "impact": "...",
    "likelihood": "Medium",
    "mitigations": ["..."]
  }
]
```

### Schema change (database migration)

1. Create `backend/db/migrations/NNNN_description.py`
2. Implement `async def up(conn: aiosqlite.Connection) -> None`
3. Use idempotent SQL (`CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`) — migrations may run against partially-applied state
4. Do **not** call `BEGIN` or `COMMIT` — the runner owns the transaction
5. Do **not** edit `backend/db/schema.py` directly

---

## Coding standards

Full standards are in [.claude/rules/RULES.md](.claude/rules/RULES.md). Short version:

- Python 3.12+, type hints on all signatures, Pydantic v2 for all data models
- `async def` for all IO (DB, LLM, MCP, filesystem)
- No bare `except` — catch specific exceptions and log before re-raising
- No raw SQL in routes or pipeline nodes — all queries in `backend/db/crud*.py`
- No wildcard imports; no re-exports from `__init__.py` unless it's the public API
- No inline `style=` in Svelte — use Tailwind utilities and `app.css` component classes

---

## Tests

- Tests mirror source: `backend/db/crud.py` → `tests/test_db_crud.py`
- Mock external dependencies (LLM APIs, MCP) at the boundary — never mock internal functions
- No test should require network access or real API keys
- Name tests by behavior: `test_generate_threats_falls_back_to_rule_engine_on_provider_timeout`

See [TESTING.md](TESTING.md) for the full test guide including CI job descriptions.

---

## Getting help

- Open an issue on GitHub for bugs or feature requests
- Check existing issues before opening a new one
- For large changes, open an issue first to discuss the approach
