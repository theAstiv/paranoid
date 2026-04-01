## Summary

<!-- 1-3 bullet points describing what this PR does and why -->

-

## Type of change

<!-- Check all that apply -->

- [ ] `feat` — New feature (pipeline step, provider, export format, UI page)
- [ ] `fix` — Bug fix
- [ ] `refactor` — Code restructuring (no behavior change)
- [ ] `test` — Adding or updating tests
- [ ] `docs` — Documentation only
- [ ] `chore` — Dependencies, CI, build config

## What changed

<!-- Describe the technical changes. Reference specific files/modules. -->

### Files modified

| File | Change |
|------|--------|
| | |

## Architecture impact

<!-- Delete this section if not applicable -->

- [ ] New pipeline step added to `backend/pipeline/nodes.py`
- [ ] New or modified Pydantic models in `backend/models/`
- [ ] New LLM provider in `backend/providers/`
- [ ] Database schema change in `backend/db/schema.py`
- [ ] New API route in `backend/routes/`
- [ ] New export format in `backend/export/`
- [ ] Seed data changed in `seeds/`
- [ ] Frontend route or component added
- [ ] MCP/context-link changes
- [ ] Docker or CI config changes

## Prompt changes

<!-- Delete this section if no prompts were modified -->
<!-- Changes to ported STRIDE prompts require justification per RULES.md -->

- [ ] STRIDE prompts modified — **Justification:**
- [ ] MAESTRO prompts modified
- [ ] New prompt template added

## Test plan

<!-- How was this tested? Check all that apply -->

- [ ] `pytest tests/ -v` — all passing
- [ ] `ruff check backend/ cli/ tests/` — no errors
- [ ] `ruff format --check backend/ cli/ tests/` — all formatted
- [ ] New unit tests added for changed code
- [ ] Mock provider tests for pipeline changes
- [ ] Manual testing (describe below)

<!-- Describe any manual testing performed -->

## Provider compatibility

<!-- Delete this section if not applicable to LLM/provider changes -->

- [ ] Tested with Anthropic
- [ ] Tested with OpenAI
- [ ] Tested with Ollama
- [ ] Graceful fallback to rule engine verified

## Breaking changes

<!-- Delete this section if none -->

- [ ] Database migration required
- [ ] Environment variable added/changed
- [ ] API contract changed
- [ ] CLI flag added/changed

## Checklist

- [ ] Code follows [RULES.md](/.claude/rules/RULES.md) conventions
- [ ] Type hints on all function signatures
- [ ] `async def` for all IO-bound functions
- [ ] No raw SQL outside `crud.py` / `vectors.py`
- [ ] No business logic in route handlers or Pydantic models
- [ ] No new dependencies without justification
- [ ] Commit messages use conventional commits (`feat:`, `fix:`, `refactor:`, etc.)
