# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [Unreleased]

### Planned Features (v2.0+)
- Deterministic rule engine with curated threat patterns
- RAG retrieval over previously approved threats
- MCP integration for code context
- Frontend UI with Svelte + Tailwind
- PDF/Markdown export formats
- GitHub Action for CI/CD integration
- Multi-user collaboration features

---

[1.0.1]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.1
[1.0.0]: https://github.com/theAstiv/paranoid/releases/tag/v1.0.0
