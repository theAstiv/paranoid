# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command to run: `docker compose up` [Coming Soon]
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Dual Framework Support**: STRIDE (traditional) + MAESTRO (AI/ML) auto-detected or run in parallel
- **DREAD Risk Scoring**: Automatic risk assessment with 5 dimensions (0-10 scale each, averaged) for severity classification
- **Structured Input Templates**: Tagged templates for component descriptions with assumption enforcement in the prompts
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Code-as-Input**: Semantic code extraction via context-link MCP — `--code /path/to/repo` grounds threats in actual implementation
- **Image-as-Input**: Architecture diagram support via `--diagram arch.png` (vision API) or `--diagram flow.mmd` (Mermaid text)
- **Deterministic Rule Engine**: 362 curated patterns (STRIDE, MAESTRO, OWASP, MITRE ATT&CK, ATLAS, CAPEC, cloud misconfigurations) across 16 seed files — run alongside the LLM and merged into the final output
- **Persistent Results**: Every run is saved to SQLite automatically — inspect past models with `paranoid models list` / `paranoid models show`
- **Export Formats**: JSON (simple/full), SARIF (GitHub Security integration), Markdown (PRs / Confluence / Notion), PDF (security review sign-off)
- **Post-Run Export**: Re-export any saved model in any format with `paranoid models export` — run once, export many times
- **Model Management**: `paranoid models delete` removes a saved model and all its data; `paranoid models prune` bulk-deletes by age or status
- **Pre-flight Gap Analysis**: Description completeness check before running — warns about missing auth, trust boundaries, data flows, and external integrations; `--strict` exits CI with code 2 on error-severity gaps
- **Edit Context Before Threats**: Review and edit extracted assets, flows, and trust boundaries at `/models/:id/context` before or after a run; "Re-extract" re-runs only the extraction steps without regenerating threats
- **DREAD Score Editing**: Edit any threat's DREAD scores inline from the Review page — no page reload required
- **Fast Provider Routing**: Configurable `FAST_MODEL` uses a Haiku-class model for extraction and enrichment, reserving Sonnet/Opus for threat generation — cuts API cost without sacrificing quality
- **Attack Tree & Test Case Enrichment**: `--enrich` generates STRIDE/MAESTRO attack trees and Gherkin test cases per threat after the main pipeline run; included automatically in Markdown and PDF exports
- **Editable Settings (Web UI)**: Runtime configuration editing at `/settings` — change provider, model, iterations, and more without restarting; protected by optional `CONFIG_SECRET` shared secret
- **CI/CD Ready**: CLI + GitHub Action with SARIF upload for automated threat detection

## Quick Start

### Step 1: Install

Choose the method that works best for you:

**PyPI (Recommended):**
```bash
pip install paranoid-cli
paranoid --version
```

**Docker (self-hosted, web UI + CLI):**
```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid

# Configure your LLM provider
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY (or OPENAI_API_KEY)

# Build and start (first build: ~5-10 min for Go + Node + Python stages)
docker compose up --build

# Web UI
open http://localhost:8000/app

# API docs (OpenAPI)
open http://localhost:8000/docs
```

See [Running with Docker](#running-with-docker) for build args, offline builds, and CLI usage inside the container.

**Standalone Binary (No Python Required):**

Download the pre-built binary for your platform from [GitHub Releases](https://github.com/theAstiv/paranoid/releases/latest):

| Platform | Binary |
|----------|--------|
| Linux x86_64 | `paranoid-linux-x64` |
| macOS ARM64 (Apple Silicon) | `paranoid-macos-arm64` |
| Windows x64 | `paranoid-windows-x64.exe` |

```bash
# Linux/macOS
chmod +x paranoid-linux-x64
./paranoid-linux-x64 --help
```

**From Source (Development):**
```bash
git clone https://github.com/theAstiv/paranoid
cd paranoid
pip install -e .
```

### Step 2: Configure

**Option A: Interactive Wizard (Recommended)**
```bash
paranoid config init

# Follow prompts to configure:
#   - LLM Provider (Anthropic/OpenAI/Ollama)
#   - API Key
#   - Model name
#   - Default iterations

paranoid config show
```

**Option B: Environment Variables**
```bash
cp .env.example .env
```

Edit `.env` and add your provider configuration:

```bash
# Anthropic (Recommended)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxx
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514

# OR OpenAI
OPENAI_API_KEY=sk-xxxxxxxxx
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4o

# OR Ollama (fully local, no API key)
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_PROVIDER=ollama
DEFAULT_MODEL=llama3

# Optional: path to context-link binary for --code flag
# If unset, Paranoid looks for bin/context-link then PATH
CONTEXT_LINK_BINARY=/usr/local/bin/context-link

# Optional: fast model for extraction/enrichment steps (Anthropic only)
# Defaults to claude-haiku-4-5-20251001; set to same value as DEFAULT_MODEL to disable fast routing
FAST_MODEL=claude-haiku-4-5-20251001

# Optional: shared secret to protect PATCH /config (web UI settings page)
# If set, the Settings page requires this value to save any configuration change
CONFIG_SECRET=your-secret-here

# Optional: restrict CORS origins (default: * allows all)
# Comma-separated for multiple origins
CORS_ORIGINS=https://app.example.com,https://staging.example.com
```

### Step 3: Run Your First Threat Model

```bash
# Run with an example
paranoid run examples/stride-example-api-gateway.md

# With architecture diagram (Mermaid, PNG, or JPG)
paranoid run examples/stride-example-api-gateway.md \
  --diagram examples/stride-api-gateway-architecture.mmd

# With your own system description
paranoid run my-system.md

# See all options
paranoid run --help
```

**Expected Output:**
```
Configuration:
  Provider: anthropic
  Model: claude-sonnet-4-20250514
  Iterations: 3
  Framework: STRIDE

[>] summarize: Generating system summary...
[OK] summarize: Summary generated: 196 chars
[>] extract_assets: Identifying assets and entities...
[OK] extract_assets: Identified 14 assets/entities
[>] extract_flows: Extracting data flows and trust boundaries...
[OK] extract_flows: Identified 12 flows, 6 boundaries
[>] generate_threats [iter 1]: Generating threats (iteration 1/3)...
[OK] generate_threats [iter 1]: Generated 10 threats
...
[OK] complete: Pipeline complete: 2 iterations, 17 threats

================================================================================
THREAT MODEL COMPLETE
================================================================================
Total Threats:      17
Iterations:         2
Duration:           115.0 seconds
Output:             stride-example-api-gateway_threats.json
```

**Expected Runtime:**
- Claude Sonnet: ~30-60 seconds (3 iterations)
- GPT-4: ~45-90 seconds (3 iterations)
- Ollama (local): 2-5 minutes (depends on hardware)

## CLI Reference

### Running Threat Models

```bash
# Basic usage (auto-detects framework from input)
paranoid run system.md

# Structured templates (auto-detects STRIDE vs MAESTRO)
paranoid run examples/stride-example-api-gateway.md
paranoid run examples/maestro-example-rag-chatbot.md

# JSON output (simple format - lightweight, ~2-3 KB)
paranoid run system.md --output threats.json

# JSON output (full format - complete models + DREAD + events, ~45 KB)
paranoid run system.md --format full -o complete.json

# SARIF export for GitHub Security integration
paranoid run system.md --format sarif -o threats.sarif

# Markdown export for PRs, Confluence, and Notion
paranoid run system.md --format markdown -o threats.md

# Markdown export with auto-suffix (no extension needed)
paranoid run system.md --format markdown -o threats

# PDF export for security review sign-off and archival
paranoid run system.md --format pdf -o report.pdf

# PDF export with auto-suffix
paranoid run system.md --format pdf -o report

# Force dual framework (STRIDE + MAESTRO in parallel)
paranoid run system.md --maestro

# Override iteration count (1-15)
paranoid run system.md --iterations 7

# Override framework auto-detection
paranoid run system.md --framework MAESTRO

# Override provider and model for a single run (without changing config)
paranoid run system.md --provider openai --model gpt-4o
paranoid run system.md --provider anthropic --model claude-opus-4-5

# Quiet mode (suppress real-time output, show only summary)
paranoid run system.md --quiet

# Verbose mode (show detailed event data with complete models)
paranoid run system.md --verbose

# Code-as-input: ground threats in actual source code (requires context-link binary)
paranoid run system.md --code /path/to/repo

# Image-as-input: include architecture diagram (PNG/JPG via vision API)
paranoid run system.md --diagram architecture.png

# Image-as-input: Mermaid diagram as text (all providers)
paranoid run system.md --diagram flow.mmd

# Combined: description + diagram + code context
paranoid run system.md --diagram arch.png --code /path/to/repo

# Strict mode: exit code 2 if description has error-severity gaps (for CI gates)
paranoid run system.md --strict

# Gap warnings are always printed to stderr; --strict makes errors blocking
paranoid run system.md --strict --format sarif -o findings.sarif

# Generate attack trees + Gherkin test cases per threat after the pipeline run
# Requires Anthropic provider; uses FAST_MODEL (claude-haiku-4-5-20251001) if configured
paranoid run system.md --enrich

# Enrich and export to Markdown (attack trees + test cases included in output)
paranoid run system.md --enrich --format markdown -o enriched-report.md

# Enrich and export to PDF
paranoid run system.md --enrich --format pdf -o enriched-report.pdf
```

### Inspecting Saved Models

Every `paranoid run` saves its results to SQLite automatically. Use the `models` subcommand to browse and inspect past runs without re-running the pipeline.

```bash
# List recent threat models (most recent first)
paranoid models list

# Limit results
paranoid models list --limit 50

# Machine-readable JSON output
paranoid models list --json

# Show threats for a saved model — partial ID works (first 8 chars)
paranoid models show a1b2c3d4

# Full UUID also accepted
paranoid models show a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Show threats without mitigations
paranoid models show a1b2c3d4 --no-mitigations

# JSON output (model metadata + threats array)
paranoid models show a1b2c3d4 --json

# Export a saved model to Markdown (run once, export many times)
paranoid models export a1b2c3d4 --format markdown -o report.md

# Export to PDF for security review sign-off
paranoid models export a1b2c3d4 --format pdf -o report.pdf

# Export to SARIF for GitHub Security
paranoid models export a1b2c3d4 --format sarif -o findings.sarif

# Export to JSON (simple summary or full raw dump)
paranoid models export a1b2c3d4 --format simple -o threats.json
paranoid models export a1b2c3d4 --format full -o complete.json

# Default output path (no -o flag): {id_prefix}_{format}.{ext} in cwd
paranoid models export a1b2c3d4 --format markdown

# Delete a saved model and all its data (prompts for confirmation)
paranoid models delete a1b2c3d4

# Delete without prompt (for scripting/CI)
paranoid models delete a1b2c3d4 --yes

# Prune old models (older than 30 days)
paranoid models prune --older-than 30

# Prune all failed models without prompting
paranoid models prune --status failed --yes

# Combine filters: old AND failed
paranoid models prune --older-than 7 --status failed
```

**Example `models list` output:**
```
  ID          Title                 Framework  Threats  Status      Date
  --------------------------------------------------------------------------
  a1b2c3d4    api-gateway           STRIDE           23  completed   2026-04-01 14:32
  e5f6g7h8    auth-service          STRIDE           17  completed   2026-03-28 09:15
  c9d0e1f2    rag-chatbot           MAESTRO          31  completed   2026-03-25 11:04
```

**Example `models show` output:**
```
  Threat Model: api-gateway
  ============================================================
  ID:           a1b2c3d4-...
  Framework:    STRIDE
  Threats:      23
  Iterations:   3

  THREATS
  ------------------------------------------------------------
  [1] SQL Injection  (Tampering)  pending
      Target: PostgreSQL DB  |  Impact: High  |  Likelihood: Medium
      → Use parameterized queries
      → Apply input validation
  ...
```

### Configuration Management

```bash
# Interactive setup wizard
paranoid config init

# Reconfigure (overwrite existing config)
paranoid config init --force

# Display current configuration
paranoid config show

# Config file location: ~/.paranoid/config.json
```

### Version Info

```bash
# Show version, Python version, dependencies, and current configuration
paranoid version
```

## Running with Docker

The Docker image bundles all three components — FastAPI backend, Svelte frontend, and the context-link MCP binary — into a single container. The frontend is served as static files from FastAPI at `/app`.

### Standard build

```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid
cp .env.example .env           # copy and edit with your API key
docker compose up --build      # builds all three stages, then starts the server
```

First build takes roughly 5–10 minutes (Go toolchain download + Node modules + Python dependencies + fastembed model pre-bake).  Subsequent builds are fast due to Docker layer caching.

**Open the web UI:** `http://localhost:8000/app`  
**Open the API docs:** `http://localhost:8000/docs`

### Configuration

Set environment variables in `.env` (picked up automatically by `docker compose`):

```bash
# Minimum — set at least one provider key
ANTHROPIC_API_KEY=sk-ant-api03-xxx
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514

# Optional overrides (defaults shown)
DEFAULT_ITERATIONS=3
PORT=8000
LOG_LEVEL=info
CORS_ORIGINS=*
SIMILARITY_THRESHOLD=0.85

# Fast model for extraction/enrichment (Anthropic only, optional)
FAST_MODEL=claude-haiku-4-5-20251001

# Shared secret to protect the Settings PATCH /config endpoint (optional)
CONFIG_SECRET=your-secret-here
```

All variables are documented in `.env.example`.

### Build arguments

| Argument | Default | Purpose |
|---|---|---|
| `CONTEXT_LINK_VERSION` | `1.0.0` | context-link release to download from [GitHub releases](https://github.com/context-link-mcp/context-link/releases) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model to pre-bake into the image |

```bash
# Pin to a specific context-link release
CONTEXT_LINK_VERSION=1.0.0 docker compose build

# Build with a different embedding model
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5 docker compose build
```

### Building without context-link (offline / no Go toolchain)

If you can't reach GitHub at build time, remove the Go stage:

1. Comment out or delete the `context-link-builder` stage in `Dockerfile`.
2. Remove the `COPY --from=context-link-builder` line in the `final` stage.
3. Mount your own pre-built binary at runtime:

```yaml
# docker-compose.yml — uncomment this volume entry
volumes:
  - ./data:/app/data
  - /path/to/context-link:/app/bin/context-link:ro
```

The app works without the binary — the `--code` flag just logs a warning and runs without code context.

### Using the CLI inside the container

```bash
# Run a threat model against a file already inside the container
docker compose exec app paranoid run /app/examples/stride-example-api-gateway.md

# Mount a local file and run it
docker run --rm \
  -v $(pwd)/my-system.md:/workspace/system.md \
  -v $(pwd)/data:/app/data \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  paranoid-app-1 \
  paranoid run /workspace/system.md --format markdown -o /app/data/out.md
```

### Persistent data

The SQLite database is stored at `/app/data/paranoid.db` inside the container, bind-mounted to `./data/` on the host. This directory persists threat models across container restarts and image upgrades.

---

## Output Formats

### JSON Simple (default, ~2-3 KB)

Lightweight threat summaries for CI/CD dashboards and quick reviews.

```json
{
  "execution": {
    "total_threats": 17,
    "iterations_completed": 2,
    "duration_seconds": 115.0
  },
  "threats": [
    {
      "name": "JWT Token Forgery",
      "category": "Spoofing",
      "target": "API Gateway",
      "impact": "Complete authentication bypass",
      "likelihood": "Medium",
      "mitigation_count": 3
    }
  ]
}
```

### JSON Full (~45 KB)

Complete Pydantic models with DREAD scores and full pipeline event audit trail. Suitable for detailed analysis, archival, and integration with other tools.

```bash
paranoid run system.md --format full -o complete.json
```

### Markdown (~4–15 KB)

Human-readable reports for PRs, Confluence, Notion, and security review documents. Contains a summary table, per-category threat sections, DREAD scores, and tagged mitigations.

```bash
paranoid run system.md --format markdown -o threats.md
```

Output structure:
```markdown
# Threat Model: my-system

**Framework:** STRIDE | **Model ID:** `a1b2c3d4` | **Generated:** 2026-04-02

## Summary
| # | Threat | Category | Target | Likelihood | DREAD |
...

## Threats

### Tampering

#### 1. SQL Injection
**Target:** Database | **Likelihood:** High | **Impact:** Data breach
**DREAD:** 7.5/10 *(D:8 R:7 E:8 A:6 Di:7)*

> An attacker exploits unparameterized queries...

**Mitigations:**
- [P] Use parameterized queries / prepared statements
- [D] Enable query anomaly logging
```

Pass `include_header=False` when calling `export_markdown()` directly to omit the H1 heading and metadata block for embedding into existing documents.

### PDF (~50–200 KB)

Structured PDF reports for security review sign-off, archival, and sharing with stakeholders who don't use Markdown. Contains the same content as the Markdown export: title, metadata, summary table, per-category threat sections, DREAD scores, and tagged mitigations. Produced via reportlab — no external binaries required.

```bash
paranoid run system.md --format pdf -o report.pdf
paranoid models export a1b2c3d4 --format pdf -o report.pdf
```

### SARIF (GitHub Security Integration)

SARIF 2.1.0 format for GitHub Security tab, GitLab, VS Code, and Azure DevOps:

```bash
paranoid run system.md --format sarif -o threats.sarif
```

**GitHub Actions Integration:**

Use the official Paranoid action for zero-config SARIF upload to the GitHub Security tab:

```yaml
name: Threat Model

on: [push, pull_request]

permissions:
  security-events: write
  contents: read

jobs:
  threat-model:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Paranoid threat modeling
        id: paranoid
        uses: theAstiv/paranoid@v1.4.0
        with:
          description-file: docs/system-description.md
          provider: anthropic
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          framework: STRIDE
          iterations: 3

      - name: Upload SARIF to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: ${{ steps.paranoid.outputs.sarif-file }}
```

**Action inputs:**

| Input | Default | Description |
|-------|---------|-------------|
| `description-file` | — | Path to system description (`.md` / `.txt`), relative to repo root |
| `provider` | `anthropic` | `anthropic`, `openai`, or `ollama` |
| `api-key` | — | Provider API key; omit for Ollama |
| `model` | provider default | Model override (e.g. `claude-sonnet-4-5`, `gpt-4o`) |
| `framework` | `STRIDE` | `STRIDE` or `MAESTRO` |
| `iterations` | `3` | Pipeline iterations (1–15) |
| `sarif-output` | `paranoid-results.sarif` | SARIF output path |
| `strict` | `false` | Exit 2 on error-severity description gaps |
| `fail-on-findings` | `false` | Fail the step if any threats are found |

## Code-as-Input (`--code`)

Ground threats in actual source code using the context-link MCP binary. When `--code` is provided, Paranoid extracts a semantically relevant slice of the codebase and threads it through every pipeline node.

```bash
paranoid run system.md --code /path/to/repo
paranoid run system.md --code /path/to/repo --iterations 5
paranoid run system.md --diagram arch.png --code /path/to/repo  # combined
```

**How it works:**

1. **Three-tier extraction funnel** (50KB budget, ~12.5K tokens):
   - Semantic search: `semantic_search_symbols` finds symbols relevant to the threat model description
   - Code body extraction: `get_code_by_symbol` fetches full source for top results
   - File skeletons: `get_file_skeleton` fills remaining budget with structural outlines

2. **Code summary step**: `_deterministic_code_summary()` extracts a focused ~2KB `CodeSummary` (tech stack, entry points, auth patterns, data stores, security observations) from `CodeContext` using file-extension mapping, import scanning, and keyword matching — no LLM call required. `summarize_code()` (LLM-backed) is available as an opt-in upgrade path when pattern matching isn't sufficient.

3. **Full pipeline threading**: The `CodeSummary` is passed to all downstream nodes — `extract_assets`, `extract_flows`, `generate_threats`, and `gap_analysis` — so threats reference actual implementation details.

4. **Deterministic extraction**: `_deterministic_code_summary()` covers tech stack from file extensions, HTTP routes from decorator patterns, auth/DB/HTTP-client keywords, and security anti-patterns (`eval()`, `pickle.load`, `shell=True`, SQL string concatenation). The pipeline never silently drops code context.

**Installing context-link:**

context-link is a standalone Go binary that indexes your repository and serves an MCP tool interface over stdio. Get it from [github.com/context-link-mcp/context-link](https://github.com/context-link-mcp/context-link):

```bash
# Option 1: pre-built binary (recommended — no Go toolchain required)
# Download the binary for your platform from the GitHub Releases page:
# https://github.com/context-link-mcp/context-link/releases/latest
# Then place it at bin/context-link or add it to PATH.

# Option 2: build from source (requires Go 1.22+)
git clone https://github.com/context-link-mcp/context-link
cd context-link
CGO_ENABLED=1 go build -o context-link ./cmd/context-link
# Move the resulting binary to bin/context-link or PATH
```

**Requirements:**

- context-link binary at `bin/context-link` (relative to working directory), on `PATH`, or at the path set by `CONTEXT_LINK_BINARY`
- Binary discovery order: explicit `CONTEXT_LINK_BINARY` env var → `./bin/context-link` → `shutil.which("context-link")`
- If the binary is not found, Paranoid logs a warning and continues without code context

**Error handling**: Every MCP failure degrades gracefully — binary not found, subprocess crash, tool call error, and index timeout all produce a warning and allow the pipeline to continue with text-only input.

---

## Image-as-Input (`--diagram`)

Supply an architecture diagram alongside your text description. Paranoid passes it to every pipeline node for richer threat coverage.

```bash
# PNG or JPG via vision API
paranoid run system.md --diagram architecture.png
paranoid run system.md --diagram architecture.jpg

# Mermaid (.mmd) as text — works with all providers
paranoid run system.md --diagram flow.mmd

# Combined with code context
paranoid run system.md --diagram arch.png --code /path/to/repo
```

**Supported formats:**

| Format | Mechanism | Size Limit |
|--------|-----------|------------|
| PNG | Vision content block (base64) | 5MB |
| JPG/JPEG | Vision content block (base64) | 5MB |
| Mermaid `.mmd` | `<architecture_diagram>` XML tag (text) | 100KB |

**Provider support:**

| Provider | PNG/JPG | Mermaid |
|----------|---------|---------|
| Anthropic (all models) | Full support | Full support |
| OpenAI `gpt-4o`, `gpt-4o-mini` | Full support | Full support |
| OpenAI other models | Not supported (use gpt-4o) | Full support |
| Ollama | Logs warning, continues without image | Full support |

**How it works:**

- **PNG/JPG**: The image is base64-encoded and passed as a vision content block in the provider's native format (Anthropic `image` content block; OpenAI `image_url` data URI). Each prompt's `<architecture_diagram>` instruction is replaced with a vision-specific directive.
- **Mermaid**: The `.mmd` file is read as UTF-8 text and injected as `<architecture_diagram>` XML in the prompt. All providers parse Mermaid syntax natively — no rendering required.
- **Pipeline threading**: `DiagramData` threads through all 5 pipeline nodes: `summarize`, `extract_assets`, `extract_flows`, `generate_threats`, and `gap_analysis`.

---

## Structured Input Templates

Paranoid supports rich XML-tagged templates for better context and assumption enforcement. See [Input-template.md](Input-template.md) for the full template reference and [examples/](examples/) for working examples.

**STRIDE Template** (traditional systems): Component description with technology stack, interfaces, data handling, and 6 structured assumption sections.

**MAESTRO Template** (AI/ML systems): Extended component description with mission alignment, agent profile, and 9 structured assumption sections.

## Model Configuration

**Use Claude Sonnet (or newer) for reliable structured output generation.**

| Model | Status | Notes |
|-------|--------|-------|
| `claude-sonnet-4-20250514` | Recommended | Validated end-to-end, reliable for production |
| `claude-haiku-4-5-20251001` | Not recommended as main model | Fails with JSON parsing errors on complex threat outputs; recommended as `FAST_MODEL` for extraction/enrichment steps |
| `gpt-4o` | Supported | Works well, also supports vision (`--diagram`) |
| Ollama (Llama 3 70B+) | Supported | Fully local, no external API calls |

## Architecture

- **Backend**: FastAPI + SQLite + sqlite-vec (loaded via `sqlite_vec.loadable_path()` — works on Windows without manual DLL installation)
- **Frontend**: Svelte + Tailwind SPA with svelte-spa-router — implemented (see `frontend/`); available when running the web server (`uvicorn backend.main:app`)
- **LLM Providers**: Anthropic / OpenAI / Ollama (protocol-based, swappable)
- **Pipeline**: Plain async functions (no LangChain, no LangGraph)
- **Embeddings**: Local via fastembed (ONNX, BAAI/bge-small-en-v1.5)
- **Models**: Pydantic v2 for all data validation
- **Frameworks**: STRIDE (traditional) + MAESTRO (AI/ML security)
- **Code context**: context-link MCP binary (Go) + `MCPCodeExtractor` async context manager
- **Image input**: `backend/image/` package — `encoder.py` (PNG/JPG base64), `mermaid.py` (text load), `validation.py` (size/format)

**Python API:**
```python
from backend.pipeline.runner import run_pipeline_for_model
from backend.providers.anthropic import AnthropicProvider
from backend.models.enums import Framework

provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="your-key")

async for event in run_pipeline_for_model(
    model_id="web-app-001",
    description="E-commerce web application...",
    framework=Framework.STRIDE,
    provider=provider,
    max_iterations=3,
):
    print(f"[{event.step}] {event.message}")
```

## Testing

```bash
# Run unit/integration tests (no API key required)
pytest tests/ -v

# Run end-to-end pipeline test (requires ANTHROPIC_API_KEY)
pytest tests/test_pipeline_e2e.py -v

# Validate structured input parser (no API key required)
python examples/test_structured_input.py

# Lint
ruff check backend/ cli/
ruff format backend/ cli/
```

## Troubleshooting

**Authentication errors:**
- Check your API key is correct in `.env` or `~/.paranoid/config.json`
- For Anthropic, ensure billing is set up and key starts with `sk-ant-api03-`

**Module not found:**
```bash
pip install -e .  # or: pip install paranoid-cli
```

**Ollama connection refused:**
```bash
ollama serve  # start Ollama first, then run paranoid
```

**`--code` flag: context-link binary not found:**

Install context-link from [github.com/context-link-mcp/context-link](https://github.com/context-link-mcp/context-link) (pre-built binaries on the Releases page), then make it available to Paranoid:

```bash
# Option 1: set env var pointing to the binary
export CONTEXT_LINK_BINARY=/path/to/context-link

# Option 2: place binary at bin/context-link relative to working directory

# Option 3: add context-link to PATH
```
If the binary is missing, Paranoid logs a warning and continues without code context.

**sqlite-vec not loading (Windows "module not found"):**

This was a known issue on Windows where a bare `vec0` extension name was used. It is fixed in the current release — the extension is now loaded via the absolute path from the bundled `sqlite-vec` Python package (`sqlite_vec.loadable_path()`), which resolves correctly on all platforms. No manual DLL installation required; `pip install paranoid-cli` includes everything.

**`--diagram` with OpenAI and vision errors:**
Only `gpt-4o` and `gpt-4o-mini` support JSON structured output together with vision. Other OpenAI models that support vision do not support JSON mode simultaneously. Switch to `gpt-4o` or use Anthropic.

**`--diagram` with Ollama:**
Ollama does not support vision for most models. Paranoid logs a warning and continues without the image. Use `--diagram flow.mmd` (Mermaid text) instead — all providers support Mermaid.

**macOS binary "developer cannot be verified":**
```bash
xattr -d com.apple.quarantine paranoid-macos-arm64
```

**Windows "Windows protected your PC":**
Click "More info" then "Run anyway", or add an exception in Windows Defender.

## Platform Support

| Platform | PyPI | Docker | Binary |
|----------|------|--------|--------|
| Ubuntu 20.04+ | Yes | Yes | Yes |
| Debian 11+ | Yes | Yes | Yes |
| RHEL 8+ | Yes | Yes | Yes |
| macOS 11+ (Intel) | Yes | Yes | No |
| macOS 11+ (ARM64) | Yes | Yes | Yes |
| Windows 10+ | Yes | Yes | Yes |
| WSL2 | Yes | Yes | Yes |

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — Release history
- [Input-template.md](Input-template.md) — Structured input template reference
- [examples/](examples/) — Working STRIDE and MAESTRO examples
- [RELEASE.md](RELEASE.md) — Maintainer release checklist

**Developer docs:**
- [.claude/rules/CLAUDE.md](.claude/rules/CLAUDE.md) — Project structure and conventions
- [.claude/rules/RULES.md](.claude/rules/RULES.md) — Coding standards
- [.claude/rules/tech-decision-rationale.md](.claude/rules/tech-decision-rationale.md) — Architecture decisions

## Development Status

**v1.4.0** — CLI production-ready, available on [PyPI](https://pypi.org/project/paranoid-cli/) and as standalone binaries.

**Completed:** Core pipeline (8 nodes, iteration logic, SSE, dual framework), LLM providers (Anthropic/OpenAI/Ollama), STRIDE + MAESTRO prompts, structured input templates, JSON + SARIF + Markdown + PDF export, DREAD scoring, CLI with config wizard, code-as-input via context-link MCP (`--code`), image-as-input via vision API and Mermaid text (`--diagram`), deterministic rule engine (362 curated patterns across 16 seed files, RAG retrieval), provider offline fallback (rule-engine-only mode), Anthropic prompt caching (~20–30% token reduction), full SQLite persistence (every run saved with assets/flows/threats/DREAD), full CRUD for all 12 schema entities, `paranoid models list/show/export/delete/prune` commands, `--provider`/`--model` run-time overrides, REST API (22+ routes with SSE and full CRUD), Svelte + Tailwind frontend (all pages and components implemented), Docker Compose deployment (3-stage build: Go + Node + Python, web UI served at `/app`), packaging and release automation, fast provider routing (`FAST_MODEL` for extraction/enrichment), `--enrich` CLI flag (attack trees + Gherkin test cases per threat), enrichment included in Markdown/PDF exports, editable Settings UI with `CONFIG_SECRET` protection.

**Future (v2.0+):** Multi-user collaboration.

## License

Apache 2.0
