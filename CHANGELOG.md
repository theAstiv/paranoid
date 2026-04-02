# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **`summarize_code()` pipeline node** — condenses raw `CodeContext` into a ~2KB `CodeSummary` (tech stack, entry points, auth patterns, data stores, external dependencies, security observations); runs concurrently with `summarize()` via `asyncio.gather()`
- **`_deterministic_code_summary()` fallback** — when `summarize_code()` LLM call fails, extracts `CodeSummary` from file extensions, import patterns, and keyword matches; never returns `None`
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

## [Planned] - v2.0+

- REST API routes (model CRUD, pipeline SSE, threat approval)
- Frontend UI with Svelte + Tailwind
- Provider offline fallback (rule-engine-only mode when LLM unavailable)
- PDF/Markdown export formats
- Multi-user collaboration features

---

[1.3.0]: https://github.com/theAstiv/paranoid/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/theAstiv/paranoid/releases/tag/v1.2.1
[1.1.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.1.0
[1.0.1]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.1
[1.0.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.0
