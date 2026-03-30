# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

- Deterministic rule engine with curated threat patterns
- RAG retrieval over previously approved threats
- Frontend UI with Svelte + Tailwind
- PDF/Markdown export formats
- Multi-user collaboration features

---

[1.1.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.1.0
[1.0.1]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.1
[1.0.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.0
[Unreleased]: https://github.com/theAstiv/paranoid/compare/v1.1.0...HEAD
