# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 1.5.1-dev

### Added

- **MediaDrop checklist threshold checked on Claude** — the 0.81 match threshold (calibrated on gpt-4.1) was checked against 3 hand-graded Sonnet 5.5 runs on Bedrock and kept for both families: 0 false positives, 12 misses of 54 graded positives. The Sonnet runs had only one negative, so the false-positive side still rests on gpt-4.1, and Claude recall is approximate (about ±3 items per run). Neither family caught MD-19 (shared webhook HMAC key lets one partner forge deliveries to others) on any run. Bench fixture and docs only; no product change

- **OpenAI reasoning effort, for GPT-6 (Sol/Luna) directly and on Bedrock** — new opt-in `OPENAI_REASONING_EFFORT` (`none`/`low`/`medium`/`high`/`xhigh`/`max`). The OpenAI provider sends it as `reasoning_effort`; OpenAI-family models on Bedrock (matched on the model ID: `openai.` or `gpt-`) get `reasoning_effort` in `additionalModelRequestFields`. Any level other than `none` omits `temperature`, which GPT-6 models reject once reasoning is on (they default to `medium`). The OpenAI provider now also drops `temperature` or `reasoning_effort`, and switches `max_tokens` to `max_completion_tokens`, after one failed call if the model rejects them, and remembers it, like the Anthropic and Bedrock providers; before this a GPT-6 model would 400 on every step and the run would fall back to the rule engine. The provider's `effort` (shown in the Run Summary) reports the level actually in effect. Unset changes nothing for `gpt-4.1`/`gpt-4o`. Never sent to the fast model, and `ANTHROPIC_EFFORT` never reaches OpenAI models. **Unverified live:** the Bedrock field name is an assumption carried over from gpt-oss, and no GPT-6 call has been made; the fallback is what keeps a wrong guess from failing a run. Bench: new slots `GPT_SOL`, `GPT_LUNA` (Bedrock) and `GPT_SOL_DIRECT`, `GPT_LUNA_DIRECT` (direct; no default model IDs), `OPENAI_REASONING_EFFORT` recorded in each run's env snapshot

- **Coverage guard and stop reporting** (B3, BB-15, BB-16) — when gap analysis says "stop" (or the STRIDE-balanced shortcut would) while a STRIDE category has **no LLM threats**, or an *applicable* MAESTRO category (from the B2 asset tags) has none, the run now takes **one** targeted extra pass per run, with a gap text naming the empty category (and, for MAESTRO, the components that made it applicable). It never fires on the last iteration (so never with `-n 1`), a MAESTRO category with no matching component never triggers it, and "unknown applicability" (no asset matched a rule) never triggers it. If the category is still empty afterwards, or dedup saturation fires, the stop is accepted and recorded. Seeded, rule-engine and dependency threats don't count as coverage. The run's usage summary (`usage` on `GET /models/{id}`, the COMPLETE event, the CLI summary and the Results "Run Summary" card) now carries `stopped_reason`, which survives a page reload, and a `coverage_guard` report: whether the guard fired, which categories still had no LLM threats, and which MAESTRO categories were N/A. **Cost:** a run that would have stopped with an empty category now spends one more iteration (one `generate_threats` call, two in a hybrid run, plus a gap call unless it was the last iteration); runs with no empty category are unchanged. No schema migration, no prompt template change

- **Real-malware recall benchmark (BM1)** — `python -m tests.bench.malware` runs the dependency engine over 20 real malicious npm packages from DataDog's `malicious-software-packages-dataset` (`tests/bench/fixtures/bm1-samples.json`, fetched as encrypted zips by `scripts/fetch_bm1_samples.py`; never installed or run). Compromised releases are judged against their previous clean release, scanned as a control. First result (2026-10-15): 12/20 flagged, compromised releases 9/14 and malicious-intent packages 3/6, every miss named in `docs/benchmarks.md` §7.4. Bench code and docs only; no product change

- **MAESTRO applicability per asset** (B2, migration 0014) — `assets` gains `maestro_categories`, a JSON list of the MAESTRO categories the asset makes applicable, derived from its name and description by deterministic keyword rules in `backend/pipeline/nodes/maestro_tags.py` (no LLM call; conservative, so a miss is preferred to a wrong tag). Tags are filled on save, on asset create/edit and once at startup for older models. MAESTRO `generate_threats` now receives an `<applicable_maestro_categories>` block naming the applicable categories and those with no matching component (input only: the output schema and the cached shared context are unchanged; no block when nothing matched). New `GET /models/{id}/maestro-coverage` (viewer) and a `maestro_coverage` object plus decoded `maestro_categories` in the JSON export give each of the 13 categories a status: covered, not covered, N/A (no component in the model) or not assessed (no asset could be tagged). Results shows a MAESTRO coverage panel for MAESTRO/hybrid models. Also fixes the web pipeline's save step, which stored `maestro_category = NULL` for every threat (only the CLI path stored it), so MAESTRO runs started from the UI had no categories to report; models saved earlier keep NULL categories and show as Not covered until re-run. Rejected threats don't count as coverage. The backfill re-runs when the tagging rules change. No change to threat counts or cost; the coverage guard (B3) is what will use the applicable set. **Known limitation (10-15 live runs):** the vocabulary misses some categories that do have threats. Supply Chain only knows *model* supply chain (pretrained models, model hubs), while the rule engine also files software supply-chain threats there, so a MAESTRO run with dependencies usually shows Supply Chain as N/A in the Run Summary even though the coverage panel lists its threats. Generic monitoring and domain-implied fairness are missed too. The coverage panel is unaffected (a category with threats always counts as covered), but an N/A category gets no coverage-guard pass

- **Flows, trust boundaries and threats link to their assets** (#13, migration 0013) — `flows` and `trust_boundaries` gain `source_asset_id` / `target_asset_id`, and `threats` gains `target_asset_id` (all `ON DELETE SET NULL`, so deleting an asset falls back to the original text). Links are derived after extraction by local name matching (exact, then normalised, then the asset named earliest in the text) — the LLM prompts and schemas are unchanged and a model can't set a link. A tie between two assets stays unlinked rather than guessed. Links are filled after each pipeline save and when flows, boundaries, assets or a threat's target are edited; models saved before this release are linked once at startup. The IDs appear in the flows/trust-boundaries/threats API responses and the JSON export; Results and the threat card show a linked endpoint as an accent chip, unlinked text as before. Measured on saved models: 90% of flow endpoints and 89% of boundary endpoints resolved on the messy dev database. On fresh runs (10-15, Sonnet 5.5 / Haiku 5.5 on Bedrock, `gpt-6-luna`, gpt-4.1) most runs resolved every endpoint, but 2 of 6 Bedrock runs resolved only 20% and 46%: the extractor sometimes returns no component assets to link to, or names a flow endpoint in shorthand ("API container" for the asset "Express API container"), which the resolver deliberately doesn't guess. `scripts/measure_component_resolution.py <db copy>` reproduces the numbers

### Security

- **Mermaid sanitizer could rebuild what it removed** (BB-12, CodeQL #10–14) — the pre-render clean-up in `mermaid_sanitize.js` ran each strip once, so `<scr<script>ipt>`, `javajavascript:script:` and double-encoded entities such as `&amp;#106;avascript:` left a live tag or scheme, and `&amp;` was decoded before `&lt;`/`&gt;`. Decoding and stripping now repeat until the text stops changing (a string that never settles is rejected as empty). This is defence in depth: Mermaid's `strict` security level, its DOMPurify pass and the CSP already neutralised these in the 10-13 browser pass
- **Generated first-run admin password stays in the log** (BB-14, CodeQL #45) — decided to keep it: with `PARANOID_ADMIN_PASSWORD` unset the server logs a random password once. `docs/authentication.md` now says anyone who can read the logs can read it, and to set the variable (and rotate after first login) for shared deployments
- **Code sources were not project-scoped, and a git URL could carry credentials** (BB-19, BB-08) — with `PARANOID_REQUIRE_AUTH=true`, `GET /sources`, `GET /sources/{id}`, `GET /sources/{id}/events` and `POST /sources` needed only a login (the list showed every project's repositories), `POST /sources` stored no project, and a model run accepted a `code_source_id` from any project, so an editor of one project could feed another project's code into their model. Sources now belong to a project (`project_id` on create, default the Default Project; `?project_id=` on the list): reads need viewer, create and re-index editor, delete owner, the list only returns your projects' sources, a project-scoped token reaches only its project, and a run refuses a source from another project (`403`, with auth off too). The `(git_url, ref)` uniqueness stays instance-wide, so adding a repository another project already has returns `409`. The Code Sources page and the wizard's source step follow the active project. **Upgrade note:** every existing source sits in the Default Project (migration 0002 put it there), and a run now refuses a source from another project, with auth off too. If your models live in other projects, move each source with `PATCH /api/sources/{id}` `{"project_id": "<project id>"}` (owner of the source's project, editor of the target; admins can do both) before running those models again. Separately, `POST /sources` rejects a URL with a username or password (they were stored and returned in plain text); migration 0012 strips existing ones and gives sources without a project the Default Project. The token is moved into the encrypted PAT field only when the source has none and the URL held `user:token@` or a token with a known prefix (`ghp_`, `github_pat_`, `glpat-` …); a bare `https://alice@host` is just a username and is dropped, and for `user:app-password@` hosts that need the username, re-enter it. If stripping makes a row a duplicate, it is renamed `…#duplicate-<id>`, marked failed and must be re-added. Auth off is unchanged
- **Source ids are validated before they become file paths** (CodeQL path-injection group) — `clone_dir_for` and `index_db_for` raise `ValueError` unless the id is exactly 32 lowercase hex characters (what the server generates), instead of trusting every caller
- **CI workflow token is read-only** (BB-13) — `ci.yml` declares `permissions: contents: read`; none of its jobs writes to the repository
- **LLM endpoints callable without a login, and a server-side probe of any URL** (BB-04, BB-11) — with `PARANOID_REQUIRE_AUTH=true`, `POST /analyze/` and `POST /models/{id}/analyze` spent the operator's LLM tokens for anonymous callers (the model route also read that model's description), and `POST /config/test-provider` made the server `GET` any caller-supplied `ollama_base_url`, a reachability and timing oracle for internal hosts. `/analyze/` now needs a login, `/models/{id}/analyze` needs viewer on the model's project, and `test-provider` needs a login; probing an Ollama URL other than the configured one needs `X-Config-Secret` when `CONFIG_SECRET` is set and, with auth on, an unscoped instance admin (otherwise 403, and the URL is never contacted). The Settings page sends the config secret with the connection test. Auth off is unchanged
- **A project-scoped PAT acted with its owner's full rights** (BB-03) — `pat_project_id` was loaded but never checked, so a token scoped to project B could change, delete and add members to project A, edit its threats and bulk-update them. A scoped token is now limited to its project on every route that resolves a project: model, threat and comment routes, source reindex/delete, project and member routes, invitations, bulk status, and the project and model lists; it cannot create projects, create models elsewhere, manage tokens (it could mint an unscoped one) or use admin routes. An instance admin's scoped token is limited too. `POST /models/` also now requires editor on the target project when auth is on (a logged-in user could previously create models in any project). Notifications are not project-scoped yet (code sources are, see the BB-19 entry). Unscoped tokens keep their owner's memberships. `POST /auth/tokens` now accepts an optional `project_id` (the caller must belong to it), so scoped tokens can be created through the API. Auth off is unchanged
- **Read routes enforced no project membership with auth on** (BB-01, BB-02) — with `PARANOID_REQUIRE_AUTH=true`, `GET /models/{id}/assets|flows|threats|trust-boundaries|stats` needed no token at all, and `GET /models/{id}`, `GET /export/{id}`, `GET /threats/{id}` (+ `/attack-trees`, `/test-cases`) and `GET /models/{id}/diff` only needed *a* login, so any user could read any project's models; `GET /models/` listed every project's models. All now require viewer on the entity's project (the diff needs viewer on both models), and the list only returns models from the caller's projects (instance admins see all). Auth off is unchanged. Non-admin users no longer see pre-v2 models in the Default Project until they are added as members of it; the `require_role` docstring no longer claims a Default Project exception (BB-05)
- **Frontend lockfile refresh** — clears 7 open Dependabot alerts: `dompurify` →3.4.16 (via mermaid; IN_PLACE sanitizer issues, a mode neither mermaid nor Paranoid uses), `devalue` →5.9.4 and `source-map-js` →1.2.2 (dev/build only)
- **Frontend dependency audit** — resolved all 19 Dependabot alerts: `mermaid` →11.16.1 (CSS injection, prototype pollution, DoS), `postcss` →8.5.23 (path traversal), `vitest` →4.1.11 (path traversal via mocker), `dompurify` →3.4.13 (XSS), plus transitive patches for `undici`, `brace-expansion`, `browserslist`, `baseline-browser-mapping`
- **Vite 5→8, Svelte 4→5** — clears remaining dev-server CVEs; Svelte 5 runs in legacy mode (all existing component syntax unchanged)

### Fixed

- **Component links missed shorthand endpoint names** (BB-34) — the extractor sometimes names a flow endpoint "API container" for the asset "Express API container", which no resolver tier matched; one 10-15 run scored 46% against the 85% bar because of it. A fourth tier now links text that is the *tail* of exactly one asset name (leading modifiers dropped); a prefix ("Admin" vs "Admin Credentials"), filler-only text ("container") and a tie between two assets stay unlinked. On the saved databases it adds 39 of 4000 flow and boundary endpoints and no threat targets (`paranoid.db` flow endpoints 91%, from 90%). Models saved before this change get their missing links filled once at the next startup (the backfill is now keyed on a resolver version; existing and edited links are never touched). Not fixed: an extraction that returns no component assets at all (nothing to link to), and a prefix like "Redis" for "Redis job queue".

- **`OPENAI_REASONING_EFFORT` had no effect on GPT-6 (Sol/Luna) on Bedrock** — the provider sent the flat `reasoning_effort`, which GPT-6 rejects as an unknown parameter, so after one failed call effort was dropped and every Bedrock Sol/Luna run used the model's default effort. GPT-6 now gets the nested `additionalModelRequestFields = {"reasoning": {"effort": ...}}` (live-verified on both models at `none`, `low` and `max`); gpt-oss keeps the flat field. A rejection that names `reasoning` now also triggers the one-call fallback. Earlier Bedrock Sol/Luna benchmark numbers are default-effort runs.

- **MAESTRO applicability missed software supply chain, observability and credit/hiring decisions; the Run Summary contradicted the coverage panel** — the tagger's Supply Chain rules knew only model supply chain, Monitoring only drift, and Fairness only explicit bias wording, so threats from the LLM, the rule engine and the dependency scan landed in categories reported as "N/A (no matching component)". Added precise phrases (CI/CD, GitHub Actions, npm/PyPI, container images, ML frameworks; observability, telemetry, Grafana; credit/loan/hiring decisions). Audit logs and audit trails are deliberately not Monitoring phrases: they matched databases and key stores that only mention them; saved models re-tag on the next start. The Run Summary and CLI no longer list a category as N/A when it has any threat, and the Results page also drops categories its coverage panel shows as covered, so runs saved before this fix read correctly too. A newly applicable category (Fairness on a loan or hiring system, Supply Chain on a CI/CD or package asset, Monitoring on an observability asset) that has no LLM threat when the model stops early now makes the coverage guard spend its one extra pass (about one more `generate_threats` call plus a gap call, per the B3 entry). Models that run every iteration anyway (Sonnet 5.5 in the 10-15 runs) are unaffected; models that stop after iteration 1 (gpt-4.1) are where it shows.

- **Results page wider than the window; Mermaid message and handler-strip fixes** (BB-28, BB-26, BB-27) — flow and trust-boundary endpoint chips no longer force one line (`whitespace-nowrap`), which had made Results about 2000px wide at a 1440px viewport; they wrap inside their column, and the Results header row wraps instead of widening the page at about 1024px. A Mermaid source the sanitizer rejects (never settles) now says it was rejected during safety cleaning instead of "Mermaid source is empty." The `on*` strip now matches only the standard HTML/SVG event-handler names, so label text such as "online = true" or "once=1" survives; a handler name outside that list is left to Mermaid's strict mode, DOMPurify and the CSP, which remain the real defence. The BB-12 payload tests are unchanged.

- **GPT-6 on Bedrock failed every call on `temperature`** — Bedrock GPT-6 (Sol/Luna) rejects `temperature` whatever the reasoning effort, with "This model doesn't support the temperature field", which the Bedrock provider's retry-without-temperature check didn't recognise; and after a rejected `reasoning_effort` the retry put `temperature` back, so that fallback died too. Every step fell back to the rule engine. `temperature` is now never sent to OpenAI-family Bedrock models other than gpt-oss (decided independently of effort), and the check also matches "doesn't support" / "does not support". Verified live 2026-10-15: `reasoning_effort` in `additionalModelRequestFields` is an unknown parameter for GPT-6 on Bedrock, so `OPENAI_REASONING_EFFORT` is dropped after one failed call there (logged) until the right field name is known. gpt-oss is unchanged

- **The active project was forgotten on reload, and the wizard's description box blinked** (#141) — after selecting a project, a reload landed on the newest one instead, because `App.svelte` activated the first project and `GET /api/projects` sorts newest first. The selected project id is now kept in `localStorage` and restored on load, falling back to the first project if it's gone or you're no longer a member. The New Model wizard's description textarea carried the caret-blink animation and faded in and out continuously; removed. Frontend only

- **The gap text was lost when the model said stop** (BB-16) — on a stop the text went only into the live event, so a finished run couldn't show why it stopped. It is now saved in `gap_summaries` (the model's text, or "Coverage balanced across all STRIDE categories" for the deterministic stop; nothing is invented when there is none). The Results gap card's subtitle now says the last entry records why the run stopped
- **The CLI dropped `refusal_count` and `effort` from the usage summary** when a pre-flight call was merged into it; they are carried over now, with the new `stopped_reason` and `coverage_guard`
- **PDF export: a model title could make the server fetch a URL and hang** (BB-07) — the title went into reportlab's `Paragraph` unescaped, and reportlab parses that text as markup. `<img src="http://…"/>` in a title made the export fetch the URL synchronously, with no timeout, on the event loop: a server-side request to an address the user chooses, which also blocks every other request (pointed at the server itself, it deadlocked it). Any other tag-like text (`<img src=x onerror=…>`, `<b>` without a close) made the export fail with a 500. The title, framework, source file and category heading are now escaped like every other field in the PDF; affects the web export, `paranoid models export --format pdf` and `paranoid run --format pdf`
- **`SEED_COLLECTIONS=stride,auth,cloud` crashed every command** (BB-06) — the documented comma-separated form raised a pydantic `SettingsError` at startup (the value was JSON-decoded), so only a JSON array worked. Both forms are now accepted, and an unknown name still gets the "Unknown seed collections … Valid names" error
- **A bad diagram upload leaked a process address** (P13) — a non-image renamed `.png`/`.jpg` returned Pillow's raw message, `cannot identify image file <_io.BytesIO object at 0x…>`, in the 422 body and the CLI error. The three Pillow failure messages (unreadable, decompression bomb, truncated) are now fixed text; Pillow's detail goes to the server log
- **SARIF dependency alerts anchored outside the repo in the GitHub Action** — `paranoid run --manifest` used the manifest path as given, and the action passes absolute paths (`/github/workspace/...`), which GitHub can't resolve. The manifest anchor is now made repo-relative (against `GITHUB_WORKSPACE`, then the current directory), the same way the description file's already was
- **Structured-output recovery, shared and extended (10-11 benchmark run; #138)** — the #130/#136 shape recovery moved to `backend/providers/_recovery.py` and now also covers the **direct Anthropic provider**, which had none of it and failed outright on valid-JSON-wrong-shape responses. New shapes: the whole response nested under an extra key, as a dict or JSON string (Sonnet 5 `{"input": {...}}`, DeepSeek `{"data": "{...}"}`). A validation failure now retries with the exact field paths and the schema's expectation restated (e.g. `threats.0.cvss.attack_complexity: Input should be 'L' or 'H'`, never the model's values) on both providers; out-of-range values such as CVSS v2's `M` are still rejected, not accepted. On Bedrock, a model that accepts forced tool choice but answers in text (GPT-OSS) has its JSON text accepted, or, if it's prose, the provider switches to auto tool choice and retries, the same as when forced choice is rejected. Measured on 10-12: Sonnet 5 went from 0/3 to 3/3 runs on Bedrock, DeepSeek from 1/3 to 3/3 ([docs/benchmarks.md](docs/benchmarks.md))
- **Bedrock models that reject forced tool choice** (#124) — Opus 5.5, Sonnet 5.5 and Fable 5.1 return a 400 for forced `toolChoice`, so every structured step failed and the run fell back to the rule engine. On that `ValidationException` the provider now retries with `auto` tool choice plus an instruction to call the `respond` tool, and remembers it for the rest of the provider instance's calls
- **Bedrock structured output on Claude 5.x** (#130) — a list/object field returned as a JSON-encoded string is parsed before validation when it parses to the expected shape, and an empty tool input retries once with the instruction restated instead of failing
- **A blank `STEP_MODELS=` crashed every command** (#127) — `.env.example` ships it, so a fresh `cp .env.example .env` quickstart failed with `SettingsError`. Blank now means no overrides; anything else must be a JSON object, with an error that says so
- **`tests/test_pipeline_e2e.py` was broken** (#129) — it still passed `diagram_data=`, renamed to `diagrams` in 5a-1. (The file stays out of CI: it needs live keys and context-link.)
- **Project and user menus didn't respond to clicks** (#139) — the outside-click backdrop sat above the sidebar and header, so **New project** just closed the dropdown. The container owning an open menu now sits above the backdrop
- **MAESTRO categories were never saved** — threat generation always used the STRIDE-only schema, so a MAESTRO run's LLM had nowhere to put a MAESTRO category and persistence never passed the column anyway (the bench's `maestro_present` gate always failed). MAESTRO calls now use a schema with `maestro_category` required (and `stride_category` still required, so SARIF rule IDs and exports are unchanged); persistence writes it; rule-engine threats keep their seed's MAESTRO category; the Review card shows a MAESTRO chip next to the STRIDE one. The MAESTRO prompt now asks for the closest STRIDE category explicitly
- **CVSS missing on LLM threats in `cvss`/`both` runs** — `cvss` was optional in the response schema, and in the 10-11 e2e-web run Opus 5.5 left it out of all 10 threats despite the CVSS prompt block, so nothing was scored. cvss/both calls now use a schema where `cvss` is required, turning an omission into a validation error that providers retry rather than a silently unscored threat. No default vectors are back-filled for LLM threats: a default would be indistinguishable from an assessed vector in the UI, SARIF and the CVSS benchmarks
- **Bedrock structured output on Sonnet 5 / Haiku 5.5** — two failure shapes #130 didn't cover, found in the 10-11 benchmark run. Sonnet 5 sometimes JSON-encodes its *whole* response into one field (`gaps` = `'{"gaps": [...], "is_sufficient": false}'`); it's now unwrapped when the decoded object contains that field and every required property. Haiku 5.5 sometimes sends a malformed JSON string; a validation failure now retries with the instruction restated, naming the failed fields (names only), instead of only bumping the token budget — and it retries even when the budget is already at its cap. Still bounded by `_MAX_RETRIES`
- **`paranoid models …` never exited** — `list`, `show`, `export`, `review`, `delete` and `prune` printed their result and then hung, because the shared DB connection (aiosqlite runs each connection on a non-daemon thread) was never closed. CLI commands now go through `cli/async_runner.run_async()`, which closes it in the same event loop on every exit path; `paranoid run` uses it too, so an error or `--strict` exit after the DB opened no longer hangs either
- **Crash on Windows redirected output** — piping or redirecting CLI output on Windows (cp1252) made the `✓`/`→` success lines raise `UnicodeEncodeError` after the work was done, reported as "Unexpected error" with exit code 1. Unencodable characters are now written as `?`
- **Version drift** — `paranoid --version` said 1.3.0, `paranoid version` 1.0.0 (it looked up a distribution named `paranoid`, not `paranoid-cli`) and SARIF's `tool.driver.version` 1.1.0. All now read `backend.__version__`, pinned to `pyproject.toml` by `tests/test_version.py`

### Added

#### GitHub Action: dependency, scoring and Bedrock inputs

- New inputs `manifest`, `lockfile`, `deps-source`, `scoring-method`, `fast-model` (`none` = every step on the main model) and `aws-region`; `provider: bedrock` is accepted without an `api-key` and uses the AWS credential chain (not yet verified in a real workflow)
- The action image now ships Semgrep (pinned, isolated venv, `SEMGREP_BINARY`, same as the main image) and the `[bedrock]` extra, so the dependency inputs and the Bedrock provider work out of the box
- `tests/test_action_entrypoint.py` runs `entrypoint.sh` with a stub `paranoid` to pin the input → flag mapping and the validation errors

#### Multi-User Collaboration (Phases 0–7)

Paranoid moves from single-user to multi-user, multi-project, RBAC-gated collaboration. SQLite remains the only datastore (WAL mode + a pre-warmed reader pool for concurrency).

**Auth foundation**
- Local accounts: argon2id password hashing (`argon2-cffi`, lazy-imported so the CLI import path stays free of it), 15-minute HS256 JWT access tokens, 7-day refresh tokens with rotation + reuse detection (a stolen refresh token works exactly once — reuse revokes the entire session family)
- Personal Access Tokens (`pat_<id>_<random>`, sha256-hashed, project-scoped) for HTTP API clients (`Authorization: Bearer pat_…`). Remote CLI authentication (`--token` / `PARANOID_TOKEN`) was planned but isn't implemented; the CLI works against its local database
- `PARANOID_REQUIRE_AUTH` (default `false`): anonymous requests get synthetic owner-on-everything access, preserving pre-v2 single-user behavior; `true` requires a valid JWT or PAT on every route except `/health` and `/api/auth/*`
- Login/refresh rate-limited (10 req/60s); Login/Register pages, Bearer-header `fetch()` wrapper with silent-refresh-and-retry on 401 (including SSE streams)

**Projects, members, RBAC**
- `projects` / `project_members` / `project_invitations` tables; owner/editor/viewer roles enforced via a `require_role()` FastAPI dependency that resolves any entity (model, threat, comment, code source) back to its owning project
- Atomic, idempotent v1→v2 migration: creates a sentinel "Default Project", backfills every existing `threat_models`/`code_sources` row's `project_id`, bumps `PRAGMA user_version`
- Frontend: project selector in the sidebar, `Members.svelte` (invite/role-change/remove), `AdminUsers.svelte` (instance-admin user management)

**Comments and assignments**
- Threaded (one-level) comments and threat-model assignees, both RBAC-gated (author-only edit, author-or-editor+ moderated delete); `Comments.svelte` + `Assignees.svelte` wired into `Results.svelte`

**Cross-model RAG scoping**
- `search_similar_threats()` / `upsert_threat_vector()` now scope by `project_id`, matching `tm.project_id = ?` OR the global `source = 'seed'` bucket — a project's approved threats inform its own future runs without leaking across projects
- Approved threats are now embedded on approve (and removed on unapprove) — previously `upsert_threat_vector` was only ever called from seed loading, so approved threats never entered the RAG index at all

**Activity log and notifications**
- Append-only `activity_log` (project-scoped) and per-user `notifications` table, both instrumented best-effort across model/threat/comment/project/member/invitation mutations (a logging or notification failure never turns a successful mutation into a 500)
- `GET/PATCH /api/notifications`, `POST /api/notifications/mark-all-read`, `GET /api/projects/{id}/activity`; topbar notification bell wired to real data

**Status workflow and project defaults**
- `ModelStatus` expanded (`in_review`, `approved`, `archived` added to `pending`/`in_progress`/`completed`/`failed`) with transition validation enforced on `PATCH /api/models/{id}` (422 on an invalid transition); `Results.svelte` gained status-workflow action buttons (send to review / approve / back to completed / archive)
- Project-level `default_provider`/`default_model`/`default_iterations`/`default_temperature` (stored since the projects table was added, never read until now) now actually resolve at model-creation and pipeline-run time, with explicit request value > project default > global setting precedence; new `ProjectSettings.svelte` screen for editing them
- `GET /api/models` and model creation are now actually project-scoped end-to-end (`?project_id=` filter, `NewModel.svelte`/`Home.svelte` send/read the active project) — previously every model from every project was visible to every user regardless of the sidebar's active project

**Project dashboard**
- `GET /api/projects/{id}/dashboard`: aggregate stat counts (models, open threats, pending review, members, last run), open-threat severity breakdown (critical/high/medium/low), and an "assigned to you" list of open threats in models assigned to the caller, ordered by DREAD score
- New `Dashboard.svelte` landing screen — stat grid, segmented severity bar, activity feed, and an "assigned to you" panel linking straight into Review; added as `/dashboard` with a new sidebar entry, alongside (not replacing) the existing Threat Models list

#### AWS Bedrock Provider

A fourth LLM provider alongside Anthropic, OpenAI, and Ollama, for teams standardizing on AWS credentials instead of a separate API key.

- `backend/providers/bedrock.py` implements the shared provider protocol over the Bedrock Converse API (`toolConfig`/`toolChoice` for structured output); `boto3` is imported lazily behind the `[bedrock]` optional extra so installing it stays opt-in
- Uses the standard AWS credential chain only (`AWS_REGION`/`AWS_PROFILE`, falling back to boto3's env/profile/instance-metadata resolution) — no Bedrock-specific API key
- Retries `converse()` without `temperature` on models that reject the parameter
- `ping_bedrock()` health check, called from `POST /api/config/test-provider` and the Settings page's provider dropdown; `DEFAULT_PROVIDER=bedrock` and `FAST_MODEL_BEDROCK` select it as the active or fast-routed provider

#### Dependency Capability Engine

Static-analysis visibility into what an npm dependency can actually *do* — network access, filesystem, process spawning, dynamic code, native addons, and 6 more (11 categories total) — diffed against its own declared GitHub source, folded into the same STRIDE/MAESTRO threat model as everything else. See [the README section](../README.md#dependency-capability-engine) for the full category list and what it does and doesn't catch.

- `backend/deps/`: `resolver.py` (npm registry + GitHub ref resolution, no GitHub token required), `fetcher.py` (safe tarball fetch/extract with per-key locks, integrity checked on compressed bytes, a size-bounded LRU cache under `DEPS_CACHE_DIR`), `scanner.py` (Semgrep-based evidence building across 11 capability categories), `delta.py` (semver-jump / publisher-change / supply-chain flags between two versions), `drift.py` (npm-tarball-vs-GitHub-source comparison; provenance narrows *where* a discrepancy is excused, it never excuses a whole category), `install_hooks.py` (lifecycle-script risk heuristics), `references.py` (reachability — promotes test/example files that shipped code actually loads)
- `paranoid deps scan <pkg>@<ver> --source npm|both`, `paranoid deps diff <pkg> <v1> <v2> --source both`, `paranoid deps scan-manifest package.json` — standalone CLI, independent of the pipeline
- Pipeline integration: a new `ANALYZE_DEPENDENCIES` step runs before `summarize` when a manifest (`--manifest`/`--lockfile` on the CLI, `dependency_manifest`/`dependency_lockfile` multipart fields on `POST /{id}/run`, or an auto-detected `package.json` from a linked code source) is present; findings become **deterministic** threat-template matches (never LLM-authored provenance — `source`/`dependency_ref` are hidden from every provider's structured-output schema and force-reset after every call) merged into the same threat list with package + file:line evidence
- Server-side analysis is capped and kill-switchable: ≤ 50 resolvable direct dependencies, a wall-clock budget (`DEPS_ANALYSIS_TIMEOUT_SECONDS`, partial results on timeout rather than discarding the whole sweep), a process-wide Semgrep concurrency cap (`DEPS_MAX_CONCURRENT_SCANS`), an LRU-evicted cache budget (`DEPS_CACHE_MAX_GB`), and `DEPS_ANALYSIS_ENABLED` to disable the feature without a redeploy
- Migration `0005_dependency_scans.py`: `dependency_scans` table (one row per analyzed package) plus `threats.dependency_ref`
- UI: an optional "Dependencies" wizard step (upload manifest/lockfile or reuse the linked code source's); a Results heatmap section (packages × categories, expandable evidence, drift buckets, skip reasons); a "Dependency" chip on `ThreatCard` with `pkg@ver · file:line`
- Exports: SARIF gets a logical `npm:pkg@ver` location plus a physical location on the consumer's own manifest (not the dependency's own `file:line`, which GitHub would resolve against the wrong repo — that survives in `properties.dependencyRef` for anyone reading the raw SARIF); Markdown/PDF get a dependency-findings section
- Semgrep is an external binary (`pip install semgrep`), not a Python dependency of Paranoid — see `SEMGREP_BINARY` in [Configuration](docs/configuration.md#dependency-capability-engine)

#### Model Routing (fast/main per pipeline step)

Cheaper, faster extraction steps without downgrading the steps that write the actual threat text.

- `PipelineConfig.step_models` routes each pipeline step to a `fast` or `main` model; `generate_threats` and `gap_analysis` can never be routed to `fast` (rejected at startup if attempted)
- Per-provider fast-model defaults: `FAST_MODEL` (Anthropic, default `claude-haiku-4-5-20251001`), `FAST_MODEL_OPENAI` (default `gpt-4.1-mini`), `FAST_MODEL_BEDROCK` and `FAST_MODEL_OLLAMA` (both empty/disabled by default); any can be set to `""` or to the main model's value to turn routing off for that provider
- `STEP_MODELS` env var (JSON map, e.g. `{"extract_flows":"main"}`) and the CLI's `--fast-model`/`--step-model` override it per run; the Settings page exposes the active provider's fast-model field
- A step routed to `fast` that fails with a non-transient error (anything other than a rate limit, timeout, connection error, or 5xx) disables fast routing for the rest of that run — flagged as `fast_routing_disabled: true` in the usage summary, with a CLI warning and a Results page Run Summary chip
- Per-step model + token usage (input/output/cache-read/cache-write) is now recorded end to end: the provider protocol reports last-call usage, `pipeline_runs` persists it as an audit log, and the Results page's Run Summary breaks it down by step

#### Mermaid Rendering (ELK layout)

- Added the ELK layout engine (`@mermaid-js/layout-elk`) alongside Mermaid's default Dagre layout — the biggest single readability win for architecture diagrams with more than a handful of nodes
- `base` theme built from the `c-*` design tokens (rounded nodes, soft shadows, dashed trust-boundary clusters, IBM Plex Sans labels) instead of Mermaid's default theme
- New shared `DiagramView.svelte` (pan/zoom, fit-to-view, SVG) used for input architecture diagrams on Results, for generated attack trees, and for every diagram added since (multiple diagrams, below)
- PDF export keeps a Mermaid description (and generated attack trees) as a code block rather than rendering server-side (Mermaid needs a browser; rendering would require a headless one in the export path) — input architecture diagrams themselves are never embedded in the PDF
- `securityLevel: 'strict'` (`diagram_theme.js`) plus `mermaid_sanitize.js`'s XSS hardening (see Security, above) apply to every diagram rendered through `DiagramView`, including this new layout path

#### ATT&CK / ATLAS Technique Enrichment

Every threat — LLM-generated, rule-engine, or dependency — is now tagged with the MITRE ATT&CK / ATLAS technique(s) it maps to, not just the rule-engine's own pattern library.

- `scripts/build_techniques.py` builds `seeds/techniques/attack_enterprise.json` (173 techniques) and `atlas.json` (170) from MITRE's live ATT&CK Enterprise STIX feed and the ATLAS YAML source, with an offline fallback if the fetch fails
- A deterministic `map_techniques` pipeline step assigns technique references three ways depending on the threat's origin: a fixed `rule_id → technique` table for dependency-engine threats, a parenthesized-ID regex against the seed pattern name for rule-engine threats, and embedding similarity (cosine + keyword overlap, narrowed by a STRIDE-category tactic prior) for everything else, including LLM-generated threats
- `Threat.attack_techniques` is schema-guarded the same way dependency provenance is — hidden from every provider's structured-output schema (`SkipJsonSchema`) and force-reset after every provider call, so an LLM can't forge its own technique attribution
- Migration `0009_threats_attack_techniques.py`; SARIF `properties.tags`; a Markdown/PDF "ATT&CK/ATLAS:" line; `ThreatCard` chips linking to attack.mitre.org / atlas.mitre.org, with embedding-sourced matches shown as "suggested" rather than confirmed
- Measured precision@3 on a 10-case golden set: 0.70 (7/10) after correcting a mislabeled case and crediting parent-technique matches (0.50 exact-only). The labels were reviewed by a human on 2026-10-15 and all kept; the three misses (matcher weaknesses, not label errors) are tracked in `tests/live/test_attack_mapping_golden.py`

#### CVSS v3.1 Scoring (alongside DREAD)

- `backend/scoring/cvss31.py`: a standalone CVSS v3.1 base-score calculator (no third-party scoring library)
- Migration `0010_threats_cvss.py`: `threats.cvss_vector`/`cvss_score`/`cvss_severity`/`scoring_method` columns; `scoring_method` records whether a threat was scored with DREAD, CVSS, or both
- Dependency-engine threats get a default CVSS vector per rule; LLM-generated threats can be scored via a CVSS-specific prompt block plus a dread-only response schema that saves ~430–670 prompt tokens per `generate_threats` call versus asking for both scoring systems in one schema
- Rule-engine threats get a default CVSS vector derived from the seed pattern's STRIDE category, `impact` and `likelihood` (`rule_pattern_cvss_vector()` in `backend/rules/cvss_defaults.py`), so a `cvss`/`both` run no longer leaves them unscored. Network-reachable, scope unchanged; editable per threat like any other vector
- `POST /api/cvss/score` scores an arbitrary vector server-side (used by the UI's manual CVSS editor); `scoring_method` is selectable per run from the CLI, API, and wizard
- SARIF `security-severity` is now keyed per `(STRIDE/MAESTRO category, CVSS band)` instead of per category alone, so a Tampering threat scored 9.8 no longer inherits the severity of an unrelated low-scored Tampering threat sharing the same rule; Markdown/PDF/SARIF all show CVSS alongside DREAD when present
- UI: a CVSS badge + inline editor on `ThreatCard`/Review, and a scoring-method selector in the wizard

#### Bedrock: per-model capabilities, refusals and effort (#128, #129)

- `LLMProvider.supports_images`: Anthropic and OpenAI `True`, Ollama `False`, Bedrock per model (Claude and the vision-capable Nova sizes by default), overridable with `BEDROCK_IMAGE_MODELS`. The runner checks it per call, including for fast-routed steps, so text-only models (GPT-OSS, Qwen, DeepSeek) get a `vision_unsupported` event and Mermaid-only prompts instead of a 400 that sent the whole run to the rule engine
- `ProviderRefusalError` for Bedrock's `content_filtered` / `guardrail_intervened` / `refusal` stop reasons, previously indistinguishable from a format failure; refusals are counted separately in the usage summary and SSE stream
- `ANTHROPIC_EFFORT` now reaches Claude on Bedrock (`additionalModelRequestFields`), dropped for the rest of a provider instance if a model rejects it. The effective effort is recorded in the run's usage summary

#### SARIF from saved-model exports (#131)

- `paranoid models export --source-file` and a `source_file` query parameter on the web export give every non-dependency SARIF result a physical location (default anchor `threat-model.md`). Without one, GitHub code scanning rejected the whole upload. Invalid values (absolute paths, URL schemes, `..`) are rejected, not silently replaced

#### Benchmarks (#125, #126)

- `tests/bench/`: an env-driven live E2E and benchmark harness for AWS Bedrock and direct OpenAI runs, with spend caps, per-run isolation, gates that fail silent rule-engine fallbacks, and Markdown reports. Not part of CI or the wheel
- [docs/benchmarks.md](docs/benchmarks.md): dated, sample-sized results: an 11-model comparison, routing, multi-diagram extraction, iterations, wall time, reliability and the dependency engine

#### Multi-Diagram Support (Week 5a-1)

A run now takes 1–5 architecture diagrams instead of one, each a named view (deployment, data flow, etc.) considered together by the pipeline.

- CLI: `--diagram`/`-d` is now repeatable (`-d arch.mmd -d flow.mmd -d deployment.png`); a single `-d` still behaves exactly as before
- API: `POST /{id}/run` gains `diagrams[]` (1–5 files) and `diagram_names` (optional JSON array of labels). The singular `diagram` field is kept for one release, merged in first; sending both is allowed up to the combined 5-file limit
- Re-running or re-extracting without a new upload now reuses the model's stored diagrams instead of silently dropping them — previously the pipeline saw nothing even though Results still showed a diagram
- A stored diagram that no longer fits today's limits (e.g. saved under 4b-1's looser per-image cap) is skipped with an SSE `stored_diagram_skipped` info event rather than failing the run; the rest of the set still goes through
- Images are validated with Pillow (format match, pixel-dimension/decompression-bomb guard, full decode) instead of a magic-byte check; diagram names are sanitized server-side everywhere they're set or read back
- Anthropic/OpenAI/Bedrock providers label each image (`Image i of n: {name}`) when more than one is sent; Anthropic now caps cache_control breakpoints at one per image set instead of one per image, avoiding a 400 once combined with the system block and shared context
- The Ollama provider still never sends images (a provider limit, not a per-model one) — image diagrams are now explicitly skipped with an SSE `vision_unsupported` info event instead of silently vanishing from the prompt
- The CLI persists loaded diagrams to the database for the first time — a CLI-run model now shows its diagrams on the Results page like a web-uploaded one does
- Backend-only in this release; see Week 5a-2 below for the multi-file wizard and Results UI

#### Multi-Diagram Support (Week 5a-2) — frontend

- Wizard's diagram step now accepts up to 5 files at once (`.png`/`.jpg`/`.jpeg`/`.mmd`/`.txt`), each with an editable name, a kind chip, and an individual remove button; a rejected file (too large, wrong type, over the count/total-size caps) never affects already-accepted files
- `POST /{id}/run` is now called with `diagrams[]` + `diagram_names` from the web UI instead of the deprecated singular `diagram` field (still supported server-side for other callers, e.g. the CLI)
- Results replaces the single-diagram `<select>` with a tab strip (`role="tablist"`, arrow-key navigation) for browsing multiple diagrams
- `GET /{id}/diagrams` no longer inlines png/jpeg image bytes (`has_content: false`); Results fetches a selected diagram's content lazily via the existing `GET /{id}/diagrams/{diagram_id}` route and caches it per tab, so opening a model with several large diagrams no longer loads all of their bytes up front. A failed fetch shows a "Couldn't load diagram · Retry" state instead of retrying forever or rendering a broken image
- `DiagramView`: the ELK/Mermaid dynamic import now runs inside its own try/catch with a visible Retry action on failure (previously an import error there was unrecoverable without reloading); added a Fit-to-view button; the scroll wheel now only zooms the diagram when Ctrl/Cmd is held, otherwise the page scrolls normally

---

### Refactored

#### Migration ledger — versioned schema changes via `backend/db/migrations/`
- **`backend/db/migrations/runner.py`** — new migration ledger runner: creates `schema_migrations` table (checksum + timestamp per entry), backfills legacy v2 databases without re-running migrations, applies pending migrations in `BEGIN IMMEDIATE` transactions (ledger entry written in the same transaction, so a half-applied migration can never appear as recorded); rollback on any failure
- **`backend/db/migrations/0001_initial.py`** — full schema snapshot covering all tables, indices, and idempotent `ADD COLUMN` patches for upgrade paths (columns added by earlier inline `ALTER TABLE` patches are applied via `try/except` on `duplicate column name`)
- **`backend/db/migrations/0002_projects.py`** — Default Project backfill (extracted from the old inline `_migrate_v1_to_v2` in `schema.py`): creates sentinel UUID `00000000-0000-0000-0000-000000000000`, backfills `project_id` on `threat_models`/`code_sources`, adds admin as owner
- **`backend/db/schema.py`** — `init_database_with_connection` now delegates entirely to `run_migrations(conn)`; the old `_migrate_v1_to_v2` function and all inline `CREATE TABLE` / `ALTER TABLE` / index creation calls are removed; `SCHEMA_VERSION` constant retained as a read-only fallback for one release
- **Adding a schema change going forward**: drop `backend/db/migrations/NNNN_description.py`, implement `async def up(conn: aiosqlite.Connection) -> None` — do not call `BEGIN`/`COMMIT` inside `up()`, do not add inline patches to `schema.py`

---

### Security

#### Mermaid diagram sanitizer XSS hardening
- `frontend/src/lib/mermaid_sanitize.js` now strips `javascript:`/`vbscript:`/`data:text/html` URI schemes, embedded `<script>` tags, and `on*` event handler attributes from Mermaid diagram source before rendering, on top of the existing `click`-directive stripping
- Numeric (`&#106;`) and hex (`&#x6A;`) HTML character references are decoded before scheme-matching, closing a bypass where an entity-encoded payload (e.g. `&#106;avascript:alert(1)`) would survive the original entity-decode step (which only handled `&nbsp;`/`&amp;`/`&lt;`/`&gt;`) and reach the DOM undetected
- 24 unit tests in `mermaid_sanitize.test.js` cover each vector plus regressions (legitimate labels containing "script", arrows, subgraphs)

#### Docker container hardening
- **`cap_drop: [ALL]`** added to `docker-compose.yml` — drops every Linux capability at the compose level; the app runs as non-root uid 1000 on port 8000 and requires no elevated capabilities at runtime (`CAP_DAC_READ_SEARCH` is not in Docker's default capset, so host-mounted directory reads are unaffected; `NET_BIND_SERVICE` is dropped — privileged ports < 1024 are now explicitly off-limits)
- **`security_opt: [no-new-privileges:true]`** added to `docker-compose.yml` — prevents privilege escalation via setuid/setgid binaries inside the container
- Removed redundant `healthcheck` block from `docker-compose.yml` — Dockerfile already defines an identical `HEALTHCHECK` directive and compose inherits it automatically; having both was silent noise
- **Dockerfile `HEALTHCHECK` converted to exec form** — `CMD ["curl", "-f", "..."]` replaces `CMD curl ... || exit 1`; exec form does not depend on `/bin/sh`, making it compatible with future distroless base-image hardening; `|| exit 1` was also redundant since `curl -f` already exits non-zero on HTTP error
- **CI docker job now smoke-tests the running container** — `load: true` added to the full-image build step so the image enters the local Docker daemon; a new "Smoke-test /health endpoint" step starts the container with `--cap-drop ALL --security-opt no-new-privileges:true` and polls `http://127.0.0.1:8000/health` for up to 60 s; a teardown step runs unconditionally on `if: always()`

---

## [1.5.0] - 2026-04-19

### Added

#### Docker UX — API Key Management via Settings UI
- **Encrypted key storage**: `PATCH /api/config` now accepts `anthropic_api_key` and `openai_api_key`; values are Fernet-encrypted (AES-128-CBC + HMAC-SHA256) and persisted in a new `config` table — survive restarts, never returned in `GET` responses
- **Env-lock behaviour**: keys present in environment variables at startup are read-only in the UI; `GET /api/config` exposes `*_api_key_set: bool` and `*_api_key_source: "env" | "db" | null`; PATCH to an env-sourced field returns 400
- **`GET /api/config` extended** with `first_run: bool`, `config_secret_required: bool`, `*_api_key_set`, `*_api_key_source` fields
- **Settings.svelte redesigned**: provider-specific API key inputs with masked display, lock icon for env-sourced fields, "Replace" action, auto-save + test-connection flow, first-run amber banner (`role="status"`, `aria-live="polite"`)

#### Docker UX — Provider Liveness Probe
- **`POST /api/config/test-provider`** — tests connectivity for `anthropic`, `openai`, or `ollama`; accepts optional `api_key` / `model` / `ollama_base_url` override; always returns 200 with `{ ok, latency_ms, provider, error?, message? }`; rate-limited at 10 req/min (in-process token bucket, no Redis)
- **Auto-test on key save**: Settings UI runs test-connection immediately after saving a key; shows green latency badge or red error inline
- **Body key takes precedence** over DB-stored key over env key — allows testing a new key before committing it

#### Docker UX — First-Run Detection and Redirect
- **`first_run` flag** in `GET /api/config` — `true` when the configured provider (non-Ollama) has no API key in env or DB; recomputed live on every call so saving a key via PATCH immediately flips it without restart
- **App.svelte bootstrap**: fetches `GET /api/config` on mount; if `first_run` and not already on `/settings`, redirects to `/settings` automatically
- **First-run banner** in Settings: non-dismissible amber panel with `aria-live="polite"` — disappears the moment a valid key is saved (next config fetch returns `first_run: false`)

#### Docker UX — Code Sources (Git Repo Indexing)
- **`code_sources` table** — new schema entity: `id`, `name`, `git_url`, `ref`, `pat_ciphertext` (Fernet-encrypted), `last_index_status` (`queued` | `cloning` | `indexing` | `ready` | `failed`), `last_index_error`, `resolved_sha`, `last_indexed_at`; `UNIQUE (git_url, ref)` prevents duplicate adds (SQLite treats NULL ≠ NULL so `ref` is stored as `""` for HEAD)
- **PAT encryption**: same Fernet / PBKDF2-HMAC-SHA256 key derivation used for API keys; `CONFIG_SECRET` env var → PBKDF2-stretched Fernet key; file fallback `data/.source_key` (0600); key-source switch detection raises 409 with actionable message
- **`backend/security/source_key.py`** — `get_fernet()`, `encrypt_str()`, `decrypt_str()`, `SourceKeyUnavailableError`, `PATDecryptionError`, `KeySourceChangedError`
- **Clone + index lifecycle** (`backend/sources/manager.py`) — background `asyncio.Task` per source: `queued → cloning → indexing → ready / failed`; per-source `asyncio.Lock` prevents concurrent clone/re-index; cancellable via `asyncio.Event` for DELETE-while-indexing
  - `git clone` with `--depth 1` (shallow) for branch/tag refs, full clone for hex SHA refs
  - Hardened clone flags: `-c protocol.file.allow=never -c core.symlinks=false`; `GIT_TERMINAL_PROMPT=0` env
  - PAT injected into HTTPS URL (`x-access-token:<pat>@`); scrubbed from stderr before persisting as `last_index_error`
  - Auth failure detection: exit 128 + `HTTP 40[13]` / `authentication failed` / `access denied` regex → human-readable "Token rejected" message
  - Allowlist: `github.com`, `gitlab.com`, `bitbucket.org` + `ADDITIONAL_GIT_HOSTS` comma-separated env var (exact hostname match, no wildcards)
  - Path-containment check: every file resolved via `Path.resolve()` verified inside the clone dir — primary symlink-escape defence
  - SSE fan-out: per-source ring buffer (last 20 events, 60 s TTL after completion) replayed on reconnect; max 8 simultaneous SSE subscribers per source
  - Heartbeat events every 10 s during indexing with `elapsed_s`, `files_scanned`, `bytes_scanned`
- **`GET/POST/DELETE /api/sources`**, **`GET /api/sources/{id}`**, **`POST /api/sources/{id}/reindex`**, **`GET /api/sources/{id}/events`** (SSE) — full CRUD + lifecycle endpoints
- **`CodeSources.svelte`** (`/sources`) — management page: add-source form (name, URL, ref, PAT masked input), live status badges with spinner, SSE progress messages, re-index button (optimistic `queued` status), delete with confirmation
- **Wizard step "Code Source"** in `NewModel.svelte` — lazy-loaded dropdown of `ready` sources, Refresh button, `None` option; `code_source_id` appended to `FormData` on run
- **Pipeline wiring**: `POST /api/models/{id}/run` accepts `code_source_id` form field; validates source exists and is `ready` before opening the SSE stream (422 otherwise); runs `MCPCodeExtractor` inside the SSE generator with started/completed/failed progress events; gracefully degrades on `MCPBinaryNotFoundError` or any extraction failure; passes `code_context` to `run_pipeline_for_model`

#### CSRF Protection
- **`backend/security/csrf.py`** — pure-ASGI middleware (no body buffering, SSE-safe); rejects mutating requests (`POST`/`PATCH`/`PUT`/`DELETE`) whose `Origin` or `Referer` header is present but does not match `ALLOWED_ORIGINS`; requests with no `Origin` (curl, CLI) pass through
- **`ALLOWED_ORIGINS` env var** — comma-separated concrete origins (no `*`); default `http://localhost:8000,http://127.0.0.1:8000`; explicitly rejects `*` with a clear startup error; empty string disables CSRF protection (documented escape hatch)
- **`docker-compose.yml`** port binding changed from `"8000:8000"` to `"127.0.0.1:8000:8000"` — loopback-only on the Docker host by default; users who want LAN exposure change to `"0.0.0.0:8000:8000"`

#### GitHub Action (`action/`)
- **`action/action.yml`** — Docker container action: inputs `description-file`, `provider`, `api-key`, `model`, `framework`, `iterations`, `sarif-output`, `strict`, `fail-on-findings`; output `sarif-file`; branding `shield / purple`
- **`action/Dockerfile`** — builds on `python:3.12-slim`; installs `paranoid-cli==${PARANOID_VERSION}` from PyPI (ARG, default `1.4.0`); pre-bakes the fastembed BAAI/bge-small-en-v1.5 model; copies `entrypoint.sh`
- **`action/entrypoint.sh`** — resolves relative paths via `$GITHUB_WORKSPACE`; validates inputs; wires `api-key` to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`; skips key validation for Ollama; runs `paranoid run --format sarif --quiet`; sets `GITHUB_OUTPUT`; emits `::notice::` with threat count; exits 1 on `fail-on-findings: true` when threats found
- **`.github/workflows/example-threat-model.yml`** — `workflow_dispatch` sample showing checkout → paranoid action → `upload-sarif`
- **CI: `action-version-sync`** — asserts `ARG PARANOID_VERSION` in `action/Dockerfile` matches `pyproject.toml` version on every PR
- **CI: `action-docker-build`** — builds `action/` Docker image on every PR to catch Dockerfile/entrypoint regressions

> **Release**: bump `pyproject.toml` and `action/Dockerfile ARG PARANOID_VERSION` together in one PR. `action-docker-build` installs from a local wheel (not PyPI), so the bump PR goes green before the tag is published.



#### Fast Provider Routing
- **`FAST_MODEL` setting** (default: `claude-haiku-4-5-20251001`) — cheap Haiku-class model used for extraction steps (assets, flows) and enrichment steps (attack trees, test cases); main threat generation keeps the primary model
- **`PipelineRunner`** accepts `fast_provider: LLMProvider | None`; falls back to main provider transparently
- **`build_fast_provider()`** in `backend/routes/_helpers.py` — constructs the fast provider when provider is Anthropic, `FAST_MODEL` is set, and differs from main model
- **`AsyncExitStack`** in `run_pipeline` and `extract_model_context` routes manages both provider HTTP contexts; identity check avoids double-entry when fast provider falls back to main
- CLI `paranoid run` builds and threads `fast_provider` through the same paths as the web route

#### CLI `--enrich` Flag
- **`paranoid run --enrich`** — after the main pipeline completes, generates an attack tree and test suite for every threat; results are included in markdown and PDF exports; skipped for `--format sarif`
- Enrichment keyed by loop index (synthetic `id`) since in-memory `Threat` objects have no `id` field; the same index is injected into `threats_dicts` at export time so exporter lookups resolve correctly
- Fixed silent `AttributeError` on `t.maestro_category` for STRIDE-only runs — replaced with `getattr(t, "maestro_category", None)`
- Exception warnings now include `type(e).__name__` so failures are visible in output

#### Export Enrichment (Markdown and PDF)
- **`export_markdown()`** and **`export_pdf()`** gain `attack_trees` and `test_suites` optional params
- Markdown: Mermaid source rendered in fenced `mermaid` block; Gherkin in fenced `gherkin` block
- PDF: both rendered as monospaced line-by-line paragraphs (PDF has no native Mermaid renderer)
- **Web export route** (`GET /api/export/{id}`) now fetches attack trees and test cases from the DB per threat for markdown and PDF formats; no-op when no enrichment has been generated

#### Runtime Config Editing (`PATCH /config`)
- **`PATCH /api/config`** — mutates `default_provider`, `model`, `fast_model`, `default_iterations`, `similarity_threshold`, `ollama_base_url` in-memory (resets on restart)
- **`CONFIG_SECRET` env var** — when set, PATCH requires a matching `X-Config-Secret` request header; requests without it receive 403; GET response exposes `config_secret_required: bool` without leaking the value
- **Settings.svelte** rewritten as an editable form: draft state, save/reset, disabled state during save; CONFIG_SECRET password field shown only when `config_secret_required` is true
- `api.js`: `updateConfig(body, secret)` forwards the secret as `X-Config-Secret` header when provided

#### Frontend
- **ThreatCard.svelte** — "Test cases →" link appears alongside "Attack tree →" for approved threats

#### Gap Analysis & Description Pre-flight
- **`backend/pipeline/pre_flight.py`** — `analyze_description_gaps()` runs before every pipeline execution to surface missing description context
  - Deterministic regex checks: authentication/auth mechanism, trust boundary definitions, data flows, external integrations
  - LLM pass identifies subtler gaps (e.g. missing encryption posture, storage details); falls back gracefully to deterministic-only on `ProviderError`
  - Returns `AnalyzeDescriptionResponse` with a list of `DescriptionGap` entries (`field`, `severity: warning|error`, `message`) and an `is_sufficient` bool
- **`POST /api/models/{id}/analyze`** — pre-flight endpoint; fast check before committing to a full pipeline run
- **`paranoid run --strict`** — exits with code 2 when any error-severity gap is found; gaps are printed to stderr so JSON/SARIF stdout stays clean; SARIF output gains a `description-completeness` rule (PNR001) with per-gap results
- **NewModel.svelte gap panel** — client-side reactive analysis (four regex checks, no API round-trip) shown once description ≥ 80 chars; green border when clear, yellow with icons when gaps exist

#### Review Context Page & Edit-then-Rerun
- **`ReviewContext.svelte`** (`/models/:id/context`) — new page for reviewing and editing extracted context before running threat generation
  - Full inline CRUD for assets (name, type, description), data flows (source → target, description, type), and trust boundaries
  - **"Re-extract from description"** button streams `POST /api/models/{id}/extract` SSE events into a live progress log; re-runs only the summarise + extract steps without generating threats
  - **"Go to Review"** link navigates to the threat review page when ready
- **`POST /api/models/{id}/extract`** — SSE endpoint that runs the pipeline with `stop_after="extraction"`; clears only non-user-edited rows (`preserve_user_edits=True`) so manual edits survive re-extraction
- **Results.svelte** — adds "Edit Context" button (→ `/models/:id/context`) and "Re-run" button that rebuilds `FormData` and starts a new full pipeline SSE stream; disabled while a run is in progress

#### DREAD Score Inline Editing
- **ThreatCard.svelte** — pencil icon opens five 1–10 number inputs (Damage, Reproducibility, Exploitability, Affected Users, Discoverability); save calls `PATCH /api/threats/{id}`, updates local state optimistically, and dispatches a `dread-updated` event
- **Review.svelte** — `on:dread-updated` handler syncs the `threats` store so filter counts stay accurate without a page reload

#### Database: `user_edited` Column
- **`backend/db/schema.py`** — `user_edited INTEGER DEFAULT 0` added to `assets`, `flows`, `trust_boundaries` tables; auto-migration via `ALTER TABLE` on startup for existing databases
- **`backend/db/crud.py`** — `clear_model_data(preserve_user_edits=False)`: when `True`, deletes only rows with `user_edited = 0`; pipeline re-runs that carry forward user edits call this with `preserve_user_edits=True`

#### Frontend Tests (Vitest)
- **`frontend/src/components/DreadBadge.test.js`** (7 tests) — renders score and labels, applies colour classes for low/medium/high/critical thresholds, handles null/undefined score
- **`frontend/src/lib/stores.test.js`** (9 tests) — `notify()` sets store and auto-clears after 4 s; initial values for all shared stores; store writes accepted
- **`frontend/src/setupTests.js`** — imports `@testing-library/jest-dom` matchers

#### CI: Frontend and Docker Jobs
- **`.github/workflows/ci.yml`** — new jobs alongside the existing Python lint/test/build jobs:
  - `frontend-test` (Node 20): `npm ci && npm test` — runs the Vitest suite
  - `frontend-build` (Node 20): `npm ci && npm run build` — verifies Vite production build; uploads `frontend/dist/` as a 1-day artifact
  - `docker` (needs `frontend-test` + `frontend-build`): builds `--target frontend-builder` (hard fail, also catches Dockerfile syntax errors); then builds the full multi-stage image
- Added `concurrency` group (`ci-${{ github.ref }}`, `cancel-in-progress: true`) to cancel superseded runs on rapid pushes
- `--ignore=tests/test_pipeline_e2e.py` with explanatory comment (requires live LLM provider + context-link binary, absent in CI runners)

#### Docker deployment
- **`Dockerfile`** — 3-stage multi-stage build:
  - `context-link-builder` (golang:1.22-bookworm, CGO) — clones and compiles the context-link MCP binary; `ARG CONTEXT_LINK_REF=main` pins the branch/tag
  - `frontend-builder` (node:20-alpine) — `npm ci && npm run build`
  - `final` (python:3.12-slim) — installs Python deps, copies source and built artefacts, pre-bakes the fastembed embedding model (`ARG EMBEDDING_MODEL`), runs as non-root uid 1000
  - `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`, `FASTEMBED_CACHE_PATH`, `DB_PATH` set as ENV defaults
  - HEALTHCHECK `start_period` bumped to 60s to cover DB init + seed loading
- **`docker-compose.yml`** — single-service setup:
  - `./data:/app/data` volume for persistent SQLite
  - Complete env-var surface: adds `CORS_ORIGINS`, `SIMILARITY_THRESHOLD`, `CONTEXT_LINK_BINARY`, `FASTEMBED_CACHE_PATH`, `MAX/MIN_ITERATION_COUNT`
  - Port binding respects `PORT` env var (`${PORT:-8000}:8000`)
  - Commented-out bind-mount option for external context-link binary
- **`.dockerignore`** — excludes `.git`, `frontend/node_modules`, `frontend/dist`, `data/`, `tests/`, `examples/`, `scripts/`, `action/`, `bin/`, `.claude/`, Python bytecode

#### REST API
- **`backend/routes/`** — Full FastAPI REST API: `models.py` (14 routes: create, list, get, update, delete, run, list threats/assets/flows, stats), `threats.py` (7 routes: get, update, delete, generate attack trees/test cases), `export.py` (multi-format export endpoint), `config.py` (configuration endpoint)
- **SSE pipeline endpoint** — `POST /api/models/{id}/run` streams real-time pipeline progress as `text/event-stream`
- **Pydantic request/response models** in `backend/models/api.py` for all endpoints

#### Frontend
- **Svelte SPA** with svelte-spa-router and Tailwind CSS (`frontend/`)
  - Pages: `Home.svelte`, `NewModel.svelte`, `Results.svelte`, `Review.svelte`, `AttackTree.svelte`, `Library.svelte`, `TestCases.svelte`, `Settings.svelte`
  - Components: `Wizard.svelte`, `ThreatCard.svelte`, `DreadBadge.svelte`, `ExportMenu.svelte`, `ResourceList.svelte`, `PipelineProgress.svelte`, `McpConfig.svelte`
  - `frontend/src/lib/api.js` — fetch wrapper with SSE subscription helper
  - `frontend/src/lib/stores.js` — Svelte writable stores for shared state
  - Served as static files by FastAPI at `/app` when `frontend/dist/` is present

---

## [1.4.0] - 2026-04-12

### Added

#### Provider Offline Fallback
- Pipeline degrades gracefully to rule-engine-only mode when the LLM provider is unavailable (rate limit, auth error, timeout)
- `stopped_reason: "provider_offline"` reported in the COMPLETE SSE event; threats from any completed iterations are preserved
- **7 tests** in `tests/test_pipeline_runner.py` covering pre-loop failure, mid-iteration failure, gap-analysis failure, and provider-error-during-threats degradation

#### Seed Pattern Expansion
- **229 new seed patterns** across 8 attack categories (authentication, APIs, cloud infrastructure, data storage, ML/AI, microservices, cryptography, access control) — all 6 STRIDE categories covered for each
- **121 additional patterns**: 67 cloud-native misconfigurations (AWS S3, IAM, Lambda, GCP, Azure), 37 MITRE ATT&CK techniques mapped to STRIDE, 17 ATLAS AI/ML adversarial patterns (training-data poisoning, model inversion, prompt injection)

#### Markdown Export
- **`backend/export/markdown.py`** — `export_markdown()` produces human-readable `.md` reports suitable for PRs, Confluence, and Notion
  - Summary table (threat name, category, target, likelihood, DREAD score)
  - Per-category threat sections with full detail: DREAD breakdown `*(D:8 R:7 E:8 A:6 Di:7)*`, blockquote description, `[P]/[D]/[C]`-tagged mitigations
  - `include_header: bool = True` parameter — set to `False` to omit the H1 heading and metadata block when embedding into an existing document
  - Accepts `list[dict[str, Any]]` rather than `ThreatsList`: works with both DB row shape (flat `dread_score`, `dread_damage`, … fields) and `model_dump()` shape (nested `dread` dict). Score is computed as `sum(dread.values()) / 5.0` for the nested shape since `DreadScore.score` is a `@property` and is not serialized by `model_dump()`
- **`--format markdown`** added to `paranoid run` — exports `.md` alongside existing `simple`, `full`, `sarif` choices
  - Auto-suffix: `--output threats` → `threats.md` (mirrors existing `.sarif` auto-suffix behaviour)
  - Warning printed if no threats are available to export (consistent with SARIF behaviour)
- **9 unit tests** in `tests/test_export_markdown.py` covering flat DREAD, nested DREAD with computed score, MAESTRO threats without DREAD, empty list, `include_header=False`, source file rendering, category grouping order, and untagged mitigations

#### `paranoid models export`
- **`paranoid models export <MODEL_ID> --format <choice> [-o output]`** — re-export any saved model from SQLite in any supported format after the fact
  - Accepts full UUID or unique prefix (same resolution logic as `paranoid models show`)
  - Formats: `markdown`, `sarif`, `simple` (JSON), `full` (JSON)
  - Default output path: `{model_id[:8]}_{format}{ext}` in the current working directory when `--output` is omitted
  - Auto-suffix: output path with no extension gets the correct suffix added (`.md`, `.sarif`, `.json`)
  - **SARIF from DB**: STRIDE-only reconstruction via `Threat.model_construct(**row)` and `ThreatsList.model_construct(threats=built)` — skips Pydantic validation to avoid word-count failures on persisted descriptions; MAESTRO threats skipped with a per-threat warning; still writes a valid (empty) SARIF file when all threats are MAESTRO
  - **Simple JSON**: `{model_id, title, framework, created_at, threats[{name, category, target, impact, likelihood, dread_score, mitigation_count}]}`
  - **Full JSON**: raw `{model: {...}, threats: [...]}` dump from `crud.get_threat_model` + `crud.list_threats`
- **11 integration tests** in `tests/test_models_export.py` using `test_db` fixture: markdown from DB, MAESTRO markdown, SARIF with deserialized mitigations, MAESTRO-only SARIF (empty result + warning), empty mitigations without crash, simple/full JSON shape, default output path naming, auto-suffix

#### PDF Export
- **`backend/export/pdf.py`** — `export_pdf()` produces reportlab platypus PDF suitable for security review sign-off and stakeholder sharing
  - Summary table with `repeatRows=1` (header repeats on overflow pages), per-category threat sections, DREAD breakdowns, and `[P]/[D]/[C]`-tagged mitigations
  - Same dual-shape DREAD handling as `export_markdown()`: flat DB row shape (`dread_score` column) and nested `model_dump()` shape (`dread` dict)
  - No external binaries required — reportlab only
- **`--format pdf`** added to `paranoid run` — exports `.pdf` alongside existing choices
  - Auto-suffix: `--output report` → `report.pdf`
  - Warning printed if no threats available to export
- **`paranoid models export --format pdf`** — PDF added to post-run export format choices
- **10 tests** in `tests/test_export_pdf.py`: `%PDF` magic byte assertion, empty threat list, flat DREAD, nested DREAD, no DREAD, source_file param, multi-category grouping; plus integration tests for `_export_model_async` PDF path (writes file, auto-suffix, default path)

#### `paranoid models delete`
- **`paranoid models delete <MODEL_ID>`** — delete a saved threat model and all associated data (threats, assets, flows, trust boundaries, pipeline runs) via schema-level `ON DELETE CASCADE`
  - Accepts full UUID or unique prefix (same resolution as `models show`)
  - Shows model summary (title, ID, created date, threat count) before prompting
  - `--yes` / `-y` skips the confirmation prompt for scripting and CI
- **5 tests** in `tests/test_models_delete_prune.py`: removes model, cascades to threats, prefix resolution, not-found raises `CLIError`, ambiguous prefix raises `CLIError` (monkeypatched `find_threat_model_by_prefix`), user cancellation (monkeypatched `click.confirm`)

#### `paranoid models prune`
- **`paranoid models prune`** — bulk-delete saved threat models matching filter criteria
  - `--older-than DAYS` — delete models created more than N days ago (uses parameterized `datetime('now', ?)` SQLite call)
  - `--status [pending|completed|failed]` — delete only models with the given status
  - Filters are combinable; at least one is required (exits with `UsageError` code 2 otherwise)
  - Shows a preview list (ID prefix, date, status, title) before prompting
  - `--yes` / `-y` skips confirmation
- **`find_threat_models_for_prune`** and **`delete_threat_models_batch`** added to `backend/db/crud.py`; batch delete has an empty-list guard (returns 0 without generating invalid `IN ()` SQL)
- **9 tests** in `tests/test_models_delete_prune.py`: by status, by status (pending), by age (backdated `created_at` via raw SQL), combined age+status, no matches, batch delete, batch empty list, `find_threat_models_for_prune` filters

#### CRUD Gap Fills (`backend/db/crud.py`)
- **assets**: `get_asset`, `delete_asset`
- **flows**: `get_flow`, `update_flow`, `delete_flow`
- **trust_boundaries**: full CRUD — `create_trust_boundary`, `get_trust_boundary`, `list_trust_boundaries`, `delete_trust_boundary` (was schema-only)
- **threat_sources**: `get_threat_source`, `delete_threat_source`
- **attack_trees**: full CRUD — `create_attack_tree`, `get_attack_tree`, `list_attack_trees`, `delete_attack_tree` (was schema-only)
- **test_cases**: full CRUD — `create_test_case`, `get_test_case`, `list_test_cases`, `delete_test_case` (was schema-only)
- **24 tests** in `tests/test_db_crud_components.py` covering all new functions plus CASCADE verification (attack trees and test cases deleted when parent threat is deleted)

#### Test Coverage Additions
- **`tests/test_models_export.py`** (+1 test) — `test_export_model_async_sarif_skips_maestro_threats`: mixed STRIDE+MAESTRO model; verifies `stride_rows` filter passes only STRIDE threats to `model_construct`, MAESTRO threat is skipped, warning output includes skip count

### Performance

#### Anthropic Prompt Caching
- `build_shared_context()` assembles a stable XML prefix (diagram, description, assumptions, assets, data flows, code summary) once after `extract_flows` — sent as a `cache_control: ephemeral` block in every downstream LLM call
- Cache hit rate ~90% on cached tokens for iterations 2–N of a multi-iteration run; ~20% overall token spend reduction for 3-iteration runs, scaling to ~30% at 10+ iterations
- Non-Anthropic providers (OpenAI, Ollama) receive the shared context as a plain string — no provider-API changes required

#### Prompt Diet (~440 tokens removed per call)
- Removed 26-line QC checklist (~350 tokens) from the flow extraction prompt
- Removed STRIDE category definitions (~90 tokens per call) from the gap analysis prompt
- `stride_threats_prompt()` unified to a single function (`improve: bool`): short DREAD rubric (6 lines) on the initial pass, full rubric (25 lines) on improvement passes

#### Structural Optimisations
- **Deterministic code summary**: `_deterministic_code_summary()` replaces `asyncio.gather(summarize(), summarize_code())` — saves one LLM API call per code-context run; `summarize_code()` retained as an opt-in upgrade path in `backend/pipeline/nodes/summary.py`
- **Drop iteration images**: vision image intentionally omitted from `generate_threats()` and `gap_analysis()` iteration calls — nodes rely on assets/flows extracted during the initial vision passes, eliminating repeated image encoding overhead
- **STRIDE coverage gate**: `_is_stride_coverage_balanced()` short-circuits gap analysis when all 6 STRIDE categories reach ≥ 2 threats — skips a 1 536-token LLM round-trip and terminates the iteration loop early with `stopped_reason: "gap_satisfied"`

### Fixed
- **sqlite-vec Windows loading**: replaced bare `load_extension("vec0")` with `sqlite_vec.loadable_path()` — resolves the full absolute path to `vec0.dll`, fixing "The specified module could not be found" errors on Windows where `site-packages/sqlite_vec/` is not on the DLL search path

---

## [1.3.0] - 2026-04-02

### Added

#### Deterministic Rule Engine
- **`backend/rules/engine.py`** — keyword-based pattern matcher that runs on every pipeline execution alongside the LLM
  - `extract_keywords()` — regex-based extraction across 8 tech categories (auth, DB, cloud, ML/AI, app arch, crypto, protocols, RBAC)
  - `match_patterns()` — scores all loaded seed patterns by keyword overlap; returns top-N as `ThreatsList`
  - `_pattern_to_threat()` — converts seed pattern dicts to `Threat` objects; maps all 13 MAESTRO categories to their nearest STRIDE equivalent via `_MAESTRO_TO_STRIDE`
  - `run_rule_engine()` — standalone entry point; no LLM, no DB required
  - `fetch_rag_context()` — async; queries `search_similar_threats()` to retrieve up to 5 prior approved/seed threats as LLM context strings; degrades gracefully on DB error
  - `merge_rule_and_llm_threats()` — deduplicates rule-engine output against LLM output via cosine similarity (default threshold 0.85); appends only unique rule threats
- **`backend/pipeline/runner.py`** — rule engine wired in after all LLM iterations:
  - RAG context fetched before each iteration's `generate_threats` call (when `config.enable_rag` is true)
  - `RULE_ENGINE` added to `PipelineStep` enum
  - Merged threat count reported in pipeline completion event
- **27 tests** in `tests/test_rules.py` covering keyword extraction, pattern matching, MAESTRO→STRIDE mapping, `run_rule_engine` standalone, merge deduplication, and `fetch_rag_context` graceful failure

#### SQLite Persistence Layer
- **`backend/db/persist.py`** — `persist_pipeline_result()` non-fatal entry point; saves all pipeline artifacts in dependency order: threat model → assets → data flows → trust boundaries → threat sources → threats; sets status to `completed` on success; returns `None` (not raises) on any DB error
- **`backend/db/crud.py`** additions:
  - `create_threat_source(model_id, category, description, example)` — persists threat actors from `FlowsList.threat_sources`
  - `list_threat_sources(model_id)` — lists all threat sources for a model
  - `create_threat()` extended with 5 individual DREAD sub-score parameters: `dread_damage`, `dread_reproducibility`, `dread_exploitability`, `dread_affected_users`, `dread_discoverability` (all `float | None`)
  - `find_threat_model_by_prefix(prefix)` — resolves a short ID prefix (`WHERE id LIKE 'prefix%'`); raises `ValueError` if the prefix matches multiple models
- **`cli/commands/run.py`** — `persist_pipeline_result()` called after every run:
  - `JSONWriter` now always created (was previously gated on `--output`); file export remains opt-in
  - Persist guard: `if json_writer.assets or json_writer.flows or json_writer.threats` — partial runs (e.g. pipeline failed after `extract_assets`) are saved with whatever data is available
  - Database ID printed at end of run in normal (non-quiet) mode
- **`backend/db/vectors.py`** — fixed rowid JOIN bug in `search_similar_threats` and `upsert_threat_vector`:
  - Added `vector_rowid INTEGER` column to `threat_metadata`; stored at insert time as `hash(metadata_id) % 2^63`
  - `search_similar_threats` JOIN changed from broken subquery to `JOIN threat_metadata tm ON tv.rowid = tm.vector_rowid`
  - UPDATE path now uses stored `vector_rowid`; logs a warning for pre-migration rows with NULL `vector_rowid`
- **`backend/db/schema.py`** — `ALTER TABLE threat_metadata ADD COLUMN vector_rowid INTEGER` migration added to `init_database_with_connection()`
- **11 tests** in `tests/test_db_persist.py` covering all write paths, DREAD round-trip, `None` inputs (partial run), and DB-failure → `None` (not raise)

#### New CLI Commands: `paranoid models`
- **`paranoid models list`** — tabular list of saved threat models (short ID, title, framework, threat count, status, date)
  - `--limit N` — cap results (default: 20, max: 200)
  - `--json` — machine-readable output
- **`paranoid models show <id>`** — detailed view of a saved model with full threat list
  - Accepts full UUID or any unique prefix (e.g. `a1b2c3d4`); raises a clear error if prefix is ambiguous
  - `--no-mitigations` — suppress mitigation list
  - `--json` — model metadata + threats array as JSON

#### New `paranoid run` flags
- `--provider [anthropic|openai|ollama]` — override configured provider for a single run without editing config or `.env`
- `--model NAME` — override configured model name for a single run
- Both flags show `(overridden)` in the configuration summary printed at startup; API key re-validated after provider override

### Fixed
- **Always-persist**: runs without `--output` now correctly save to SQLite; previously `JSONWriter` was never created when no output file was requested, silently skipping all DB writes

### Changed
- `paranoid models` registered as a top-level command group in `cli/main.py`

---

## [1.2.1] - 2026-03-31

### Added

#### Testing and Build Automation
- **`scripts/build_test.py`** — Comprehensive 8-step pre-release validation system
  - Version consistency check across pyproject.toml
  - Full test suite execution (171+ tests)
  - Code quality validation (ruff check + format)
  - PyPI package build verification (wheel + source distribution)
  - Binary build via PyInstaller (single-file executable)
  - Binary smoke tests (--help, --version)
  - Dependencies verification
  - Install test in fresh virtualenv
- **`scripts/run_tests.py`** — Fast test runner for development workflow
  - `--fast` mode: Skip slow tests (~20-30s)
  - `--lint` mode: Only linting (~5s)
  - `--tests` mode: Only tests, skip lint (~1min)
  - Full validation by default (~1-2min)
- **Git hooks** — Automated quality gates
  - `pre-commit`: Runs fast tests before every commit
  - `pre-push`: Runs full test suite before push
  - Cross-platform installers: `install-hooks.sh` (Unix) and `install-hooks.bat` (Windows)
- **GitHub Actions workflows**
  - `test.yml`: Matrix testing across 3 OS × 2 Python versions (3.12, 3.13)
  - `pr-validation.yml`: PR validation with version check, linting, tests, and summary
- **Build wrappers** — One-command build validation
  - `build-test.sh` (Unix) and `build-test.bat` (Windows)
  - Auto-installs build dependencies if missing
- **Documentation**
  - `TESTING.md`: Complete testing guide with workflows and troubleshooting
  - `.github/TESTING_CHEATSHEET.md`: Quick reference for all testing commands

### Changed
- **Ruff configuration** — Expanded ignore rules from 3 to 28+ for practical release
  - Reduced linting errors from 895 to 39 non-blocking warnings
  - Added incremental type annotation adoption path (ANN*)
  - Practical complexity thresholds (PLR*)
  - False positive suppressions (S104, S608 for Docker/SQL)
  - Legacy code patterns (B904, EM101/102 for exception chaining)
- **Package configuration** — Added seeds* to distribution
  - `pyproject.toml`: Include seeds* in packages
  - `MANIFEST.in`: Recursive include for seeds/*.json
  - `package-data`: Added *.json pattern
- **Binary build** — Updated paranoid.spec
  - Added PIL and fastembed support
  - Included seeds directory as data
  - Removed PIL from excludes list

### Fixed
- **Windows Unicode encoding** — Replaced box-drawing characters (╔═╗) with ASCII (===) in build_test.py and run_tests.py to prevent UnicodeEncodeError with cp1252 codec
- **Binary path detection** — Fixed PyInstaller single-file executable path resolution in build_test.py
- **PR validation workflow** — Fixed dependency installation (removed non-existent 'build' extra)
- **Test workflow** — Removed no-op codecov upload step

---

## [1.2.0] - 2026-03-30

### Added

#### Code-as-Input (`--code`)
- **`--code PATH`** CLI flag — extracts semantically relevant code from a local repository and threads it through all pipeline nodes
- **`MCPCodeExtractor`** async context manager (`backend/mcp/client.py`) — manages context-link subprocess lifecycle over MCP stdio transport
- **Three-tier extraction funnel**: semantic symbol search → code body extraction → file skeletons, capped at 50KB (~12.5K tokens)
- **`_deterministic_code_summary()` extractor** — default code-summary path; extracts ~2KB `CodeSummary` (tech stack, entry points, auth patterns, data stores, external dependencies, security observations) from file extensions, import scanning, and keyword matching without an LLM call; replaces the previous `asyncio.gather(summarize(), summarize_code())` concurrent pattern to save one API call per run
- **`summarize_code()` pipeline node** — LLM-backed code summarization retained as an opt-in upgrade path in `backend/pipeline/nodes/summary.py`; not called by the runner by default
- **`CodeSummary` Pydantic model** (`backend/models/extended.py`) — structured condensed code representation threaded through `extract_assets`, `extract_flows`, `generate_threats`, `gap_analysis`
- **`CONTEXT_LINK_BINARY` env var** — override binary path; auto-detection order: env var → `./bin/context-link` → `shutil.which("context-link")`
- **MCP error hierarchy** (`backend/mcp/errors.py`): `MCPError` → `MCPBinaryNotFoundError`, `MCPConnectionError`, `MCPToolError`, `MCPTimeoutError`
- **Graceful degradation**: binary not found, subprocess crash, tool call error, and index timeout all produce a warning and allow the pipeline to continue with text-only input
- **Prompt updates**: STRIDE and MAESTRO prompts updated to reference `<code_summary>` in all 5 prompt functions with security-specific guidance per prompt type

#### Image-as-Input (`--diagram`)
- **`--diagram PATH`** CLI flag — loads a PNG, JPG, or Mermaid `.mmd` file and threads it through all pipeline nodes
- **Vision API support**: PNG/JPG encoded as base64 and passed as native vision content blocks (Anthropic `image` content block; OpenAI `image_url` data URI)
- **Mermaid support**: `.mmd` files loaded as UTF-8 text and injected as `<architecture_diagram>` XML tag — works with all providers including Ollama
- **`DiagramData` and `ImageContent` Pydantic models** (`backend/models/extended.py`) — carry diagram content through the pipeline
- **`DiagramFormat` enum** (`backend/models/enums.py`) — `png`, `jpeg`, `mermaid`; prevents format string typos
- **`backend/image/` package**: `encoder.py` (PNG/JPG base64 loading), `mermaid.py` (text loading), `validation.py` (size/format validation)
- **`cli/input/diagram_loader.py`** — async diagram loading entry point used by CLI
- **File size limits**: 5MB for PNG/JPG, 100KB for Mermaid (validated at CLI load time with descriptive error messages)
- **`_replace_architecture_diagram_instruction()` helper** — replaces the `<architecture_diagram>` input enumeration line in STRIDE/MAESTRO prompts with a format-specific directive when a diagram is provided, preventing conflicting instructions
- **`DiagramData` threads through 5 pipeline nodes**: `summarize`, `extract_assets`, `extract_flows`, `generate_threats`, `gap_analysis`
- **Provider support matrix**: Anthropic (all models, full vision); OpenAI `gpt-4o`/`gpt-4o-mini` (full vision); OpenAI other models (Mermaid only, logs warning for PNG/JPG); Ollama (Mermaid only, logs warning for PNG/JPG)
- **Backward compatible**: existing `architecture_diagram: str` parameter kept alongside new `diagram_data: Optional[DiagramData]`; deprecated, removal planned for v2.0

#### New `paranoid run` flags
- `--code PATH` — path to repository for MCP code extraction
- `--diagram PATH` — path to PNG, JPG, or `.mmd` architecture diagram

---

## [1.1.0] - 2026-03-29

### Added

#### Threat Deduplication
- **Embedding-based deduplication** across STRIDE + MAESTRO frameworks using cosine similarity (0.85 threshold) via existing fastembed infrastructure
- **Cross-iteration dedup** prevents duplicate threats from accumulating across iteration 2+
- **Text fallback** using difflib when embeddings fail

#### Seed Pattern Expansion
- **STRIDE patterns**: 18 → 53 (9 per category) — added XSS, CSRF, SSRF, IDOR, file upload, request smuggling, prototype pollution, ReDoS, XXE, WebSocket flooding, kernel exploits, IAM misconfig, race conditions, dependency confusion, and more
- **MAESTRO patterns**: 20 → 46 — filled gaps in Data Security, LLM Security (indirect prompt injection, jailbreaking, context window manipulation, agentic tool abuse), Pipeline Security, Fairness, Monitoring, Privacy, and Distributed ML
- **Total curated patterns**: 48 → 109
- **Partial load detection** with automatic cleanup and reload on count mismatch

#### Test Infrastructure
- **MockProvider** — in-process `LLMProvider` implementation with canned Pydantic responses for all pipeline steps, enabling full pipeline testing without API tokens
- **Test fixtures package** (`tests/fixtures/`) with 9 factory functions returning realistic threat model data
- **48 new tests** covering pipeline nodes (24), pipeline runner (7), SARIF export (6), and seed loader (11)
- **Total test count**: 65 → 113, all passing without network access

### Fixed

- **SARIF export `dread.score` bug** — `_severity_to_level` and `_generate_results` referenced nonexistent `dread.total` instead of the `DreadScore.score` property (average 0-10)
- **Threat counting bug** — runner now tracks cumulative threats across iterations instead of reporting only the last iteration's count
- **Iteration off-by-one** — explicit counter tracking avoids miscounts on early exit (gap satisfied/timeout)
- **SSE serialization** — `TypeError` when event data contained nested Pydantic models; extracted shared `backend/serialization.py` utility with full recursive conversion
- **Output file default** — `--output` no longer writes a default file when the flag is omitted; output is opt-in only
- **Config environment mutation** — rewrote `_load_merged_settings` to use pydantic-settings constructor overrides instead of mutating `os.environ`, fixing thread-safety and permanent env pollution
- **Silent parser failures** — replaced four bare `except Exception: return None` blocks in input parser with specific `ValidationError`/`AttributeError`/`TypeError`/`KeyError` handlers with logged warnings
- **Broad CLI exception catching** — replaced catch-all `except Exception` in `_run_pipeline_async` with specific handlers for `ProviderAuthError`, `ProviderRateLimitError`, and `ProviderTimeoutError` with actionable messages
- **Model string duplication** — extracted `DEFAULT_ANTHROPIC_MODEL`, `DEFAULT_OPENAI_MODEL`, `DEFAULT_OLLAMA_MODEL` constants to `cli/context.py` as single source of truth

### Changed

- **Providers now support async context managers** — `__aenter__`/`__aexit__` added to `LLMProvider` Protocol; fixes `httpx.AsyncClient` resource leak in OllamaProvider
- **`run_sync_in_executor`** — replaced deprecated `asyncio.get_event_loop()` with `get_running_loop()`, `lambda` with `functools.partial`
- **Documentation consolidated** — merged QUICKSTART.md, TESTING.md, and DISTRIBUTION.md into README.md; deleted stale STATUS.md; trimmed RELEASE.md

---

## [1.0.1] - 2026-03-24

### Fixed

- **Package metadata** - Updated author from "Astitva / StateCheck Security" to just "Astitva"
- **Documentation URLs** - Fixed remaining placeholder URLs to use actual GitHub username `theAstiv`

### Note

This is a metadata-only release. The functionality is identical to v1.0.0.

---

## [1.0.0] - 2026-03-24

### Added

#### Core Pipeline
- **STRIDE threat modeling framework** with 6 threat categories (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege)
- **MAESTRO threat modeling framework** for AI/ML systems with 9 security dimensions
- **Iterative refinement pipeline** with configurable 1-15 iteration passes
- **Gap analysis** to identify missing threat categories and drive iteration stopping
- **Dual framework mode** to run STRIDE + MAESTRO in parallel on the same system
- **DREAD risk scoring** for all threats (Damage, Reproducibility, Exploitability, Affected Users, Discoverability, 0-50 scale)
- **Structured input templates** with XML-tagged component descriptions and assumption enforcement
- **Multi-provider LLM support** (Anthropic, OpenAI, Ollama) with protocol-based abstraction
- **Event-driven pipeline** with real-time SSE event streaming
- **SARIF 2.1.0 export** for GitHub Security tab integration, PR annotations, and severity mapping from DREAD scores
- **Attack tree generation** with Mermaid diagram output
- **Test case generation** from threats with Gherkin/BDD format

#### CLI Commands
- `paranoid run INPUT_FILE` - Execute threat modeling on system descriptions
  - Auto-detects framework from XML tags (STRIDE vs MAESTRO)
  - Supports plain text `.md`/`.txt` files and structured templates
  - Real-time console output with progress indicators
  - JSON export with simple (lightweight) and full (complete) formats
  - SARIF export for GitHub Security integration
  - `--output, -o PATH` - Specify output file
  - `--format [simple|full|sarif]` - Choose output format
  - `--maestro` - Force dual framework execution
  - `--iterations, -n INT` - Override iteration count (1-15)
  - `--framework [STRIDE|MAESTRO]` - Override framework auto-detection
  - `--quiet, -q` - Suppress real-time output (CI/CD friendly)
  - `--verbose, -v` - Show detailed event data with complete Pydantic models

- `paranoid config` - Configuration management
  - `paranoid config init` - Interactive setup wizard for first-time configuration
  - `paranoid config show` - Display current configuration
  - Config file at `~/.paranoid/config.json` with secure permissions (0o600)

- `paranoid version` - Show version, Python version, dependencies, and configuration

#### Persistence & Vector Search
- **SQLite database** with schema for threat models, threats, assets, flows, pipeline runs
- **sqlite-vec integration** for vector similarity search over threat patterns
- **fastembed** for local embedding generation (ONNX, BAAI/bge-small-en-v1.5)
- **Seed data loader** for curated STRIDE, MAESTRO, and OWASP LLM Top 10 patterns

#### JSON Export Formats
- **Simple format** (default, ~2-3 KB) - Lightweight threat summaries for CI/CD dashboards
- **Full format** (~45 KB) - Complete Pydantic models with DREAD scores and event audit trail

#### Structured Input Templates
- **STRIDE template** for traditional systems with 6 assumption sections
- **MAESTRO template** for AI/ML systems with 9 assumption sections

#### Configuration System
- Environment variable support (`.env` file)
- User configuration file (`~/.paranoid/config.json`)
- Config precedence: CLI flags > Environment variables > Config file > Defaults
- Interactive wizard for first-time setup

#### LLM Providers
- **Anthropic** - Claude models via tool_use API (recommended: `claude-sonnet-4-20250514`)
- **OpenAI** - GPT models via response_format API
- **Ollama** - Local/air-gapped deployment with Llama 3, Mistral, etc.

### Fixed
- Pydantic model serialization in verbose mode (AssetsList not JSON serializable)
- Config loading precedence (environment variables properly override config file)
- Framework auto-detection from structured input templates
- JSON export format differentiation (simple vs full)

### Known Limitations
- No frontend UI (CLI-only for v1.0)
- No deterministic rule engine (seed patterns loaded but not yet used for fallback)
- No MCP integration (deferred to v2.0)
- Single-user mode (no multi-user collaboration)

---

## [Planned]

### v2.0+
- OIDC/SSO federation

---

[Unreleased]: https://github.com/theAstiv/paranoid/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/theAstiv/paranoid/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/theAstiv/paranoid/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/theAstiv/paranoid/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/theAstiv/paranoid/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/theAstiv/paranoid/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/theAstiv/paranoid/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/theAstiv/paranoid/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.0
