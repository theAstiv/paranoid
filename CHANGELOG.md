# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-03-24

### Fixed

- **Package metadata** - Updated author from "Astitva / StateCheck Security" to just "Astitva"
- **Documentation URLs** - Fixed remaining `yourusername` placeholder in RELEASE.md to use actual GitHub username `theAstiv`

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

#### CLI Commands
- `paranoid run INPUT_FILE` - Execute threat modeling on system descriptions
  - Auto-detects framework from XML tags (STRIDE vs MAESTRO)
  - Supports plain text `.md`/`.txt` files and structured templates
  - Real-time console output with progress indicators
  - JSON export with simple (lightweight) and full (complete) formats
  - `--output, -o PATH` - Specify JSON output file
  - `--format [simple|full]` - Choose output detail level
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

#### JSON Export Formats
- **Simple format** (default, ~2-3 KB) - Lightweight threat summaries for CI/CD dashboards
  - Execution metadata (iterations, duration, threat counts)
  - Lightweight threat list (name, category, target, impact, likelihood, mitigation_count)
  - No DREAD scoring, no events, no complete models

- **Full format** (~45 KB) - Complete models for detailed analysis
  - Complete Pydantic models (Assets, Flows, Threats with all fields)
  - DREAD risk assessment scores
  - Full pipeline event audit trail
  - Suitable for archival and integration with other tools

#### Structured Input Templates
- **STRIDE template** for traditional systems
  - `<component_description>` with technology stack, interfaces, data handling
  - 6 structured assumption sections (security controls, scope, focus areas)

- **MAESTRO template** for AI/ML systems
  - `<maestro_component_description>` with mission alignment, agent profile
  - 9 structured assumption sections (mission constraints, AI-specific controls, agentic considerations)

#### Configuration System
- Environment variable support (`.env` file)
- User configuration file (`~/.paranoid/config.json`)
- Config precedence: CLI flags > Environment variables > Config file > Defaults
- Interactive wizard for first-time setup
- Multi-provider configuration (Anthropic, OpenAI, Ollama)

#### LLM Providers
- **Anthropic** - Claude models via tool_use API
  - Tested: `claude-sonnet-4-20250514` (recommended)
  - Not recommended: `claude-haiku-4-5-20251001` (fails on complex outputs)

- **OpenAI** - GPT models via response_format API
  - Supports structured output with JSON schema

- **Ollama** - Local/air-gapped deployment
  - Fully local execution, no external API calls
  - Compatible with Llama 3, Mistral, and other models

#### Documentation
- Comprehensive README.md with quick start guide
- Example structured templates in `examples/` directory
- TESTING.md with validation results
- STRUCTURED_INPUT_IMPLEMENTATION.md feature guide
- Developer documentation in `.claude/` directory

### Fixed
- Pydantic model serialization in verbose mode (AssetsList not JSON serializable)
- Config loading precedence (environment variables properly override config file)
- Framework auto-detection from structured input templates
- JSON export format differentiation (simple vs full)

### Technical Details
- **Language**: Python 3.12+
- **CLI Framework**: Click 8.1.7+
- **Data Validation**: Pydantic v2
- **Async Runtime**: asyncio with aiosqlite
- **LLM SDKs**: anthropic 0.42.0+, openai 1.58.1+
- **HTTP Client**: httpx
- **Configuration**: JSON file at `~/.paranoid/config.json`

### Architecture
- Plain async functions (no LangChain, no LangGraph)
- Protocol-based LLM abstraction (3 providers, ~50 lines each)
- Event-driven pipeline with SSE streaming
- Pydantic v2 for all data contracts
- Clean separation: CLI layer → Backend pipeline → LLM providers

### Breaking Changes
- None (initial release)

### Known Limitations
- SQLite-vec not included (future: deterministic rule engine)
- No frontend UI (CLI-only for v1.0)
- No attack tree generation (future feature)
- No test case generation (future feature)
- No SARIF export (future feature)
- Single-user mode (no multi-user collaboration)

---

## [Unreleased]

### Planned Features (Future Releases)
- Deterministic rule engine with curated threat patterns (Phase 7)
- RAG retrieval over previously approved threats (Phase 6.9)
- MCP integration for code context (Phase 8)
- Frontend UI with Svelte + Tailwind (Phase 10)
- Attack tree generation
- Test case generation from threats
- SARIF export for GitHub Security tab
- PDF/Markdown export formats
- GitHub Action for CI/CD integration
- Multi-user collaboration features
- Homebrew tap distribution
- apt/deb package distribution

---

[1.0.1]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.1
[1.0.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.0
